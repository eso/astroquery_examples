from __future__ import annotations

import logging
import warnings
import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time
from astropy.table import vstack
from astroquery.eso import Eso
from PIL import Image
from matplotlib import pyplot as plt
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _normalize_product_ids(dp_id):
    if dp_id is None:
        return []
    if isinstance(dp_id, str):
        values = [v.strip() for v in dp_id.split(",")]
    else:
        try:
            values = list(dp_id)
        except TypeError:
            values = [dp_id]

    out = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, bytes):
            value = value.decode(errors="ignore")
        clean = str(value).strip()
        if clean and clean not in out:
            out.append(clean)
    return out


def _quote_sql_string(value):
    return "'" + str(value).replace("'", "''") + "'"


def _adql_sanitize_op_val(op_val):
    supported_operators = [
        "<=", ">=", "!=", "=", ">", "<",
        "not like ", "not in ", "not between ",
        "like ", "between ", "in ",
    ]
    if not isinstance(op_val, str):
        return f"= {op_val}"

    op_val = op_val.strip()
    for operator in supported_operators:
        if op_val.lower().startswith(operator):
            value = op_val[len(operator):].strip()
            return f"{operator} {value}"

    return f"= {_quote_sql_string(op_val)}"


def _build_ancillary_query(dp_ids, columns=None, column_filters=None, top=None,
                           count_only=False, order_by="", order_by_desc=True):
    table_name = "phase3v2.product_files"
    filters = dict(column_filters) if column_filters else {}

    where_parts = []
    if dp_ids:
        quoted_ids = ", ".join(_quote_sql_string(v) for v in dp_ids)
        where_parts.append(f"product_id in ({quoted_ids})")
    where_parts.extend([f"{k} {_adql_sanitize_op_val(v)}" for k, v in filters.items()])

    if isinstance(columns, str):
        selected_columns = [v.strip() for v in columns.split(",") if v.strip()]
    elif columns:
        selected_columns = list(columns)
    else:
        selected_columns = ["*"]

    if count_only:
        selected_columns = ["count(*)"]

    query = f"select {', '.join(selected_columns)} from {table_name}"
    if where_parts:
        query += " where " + " and ".join(where_parts)
    if order_by and not count_only:
        query += f" order by {order_by} {'desc' if order_by_desc else 'asc'}"
    if top is not None:
        query = query.replace("select ", f"select top {top} ", 1)
    return query


def _query_ancillary_fallback(self, dp_id=None, *, help=False, columns=None,
                              column_filters=None, ROW_LIMIT=None, **kwargs):
    table_name = "phase3v2.product_files"
    if help:
        self.list_column(table_name)
        return None

    dp_ids = _normalize_product_ids(dp_id)
    if not dp_ids:
        raise ValueError("dp_id must be specified when help=False.")

    if "maxrec" in kwargs:
        if ROW_LIMIT is not None:
            raise TypeError("Use either ROW_LIMIT or maxrec, not both.")
        ROW_LIMIT = kwargs.pop("maxrec")

    allowed_kwargs = {
        "top", "count_only", "get_query_payload", "authenticated",
        "order_by", "order_by_desc",
    }
    unknown_kwargs = set(kwargs) - allowed_kwargs
    if unknown_kwargs:
        unknown_str = ", ".join(sorted(unknown_kwargs))
        raise TypeError(f"Unexpected keyword argument(s): {unknown_str}")

    count_only = kwargs.get("count_only", False)
    query = _build_ancillary_query(
        dp_ids=dp_ids,
        columns=columns,
        column_filters=column_filters,
        top=kwargs.get("top"),
        count_only=count_only,
        order_by=kwargs.get("order_by", ""),
        order_by_desc=kwargs.get("order_by_desc", True),
    )

    if kwargs.get("get_query_payload", False):
        return query

    previous_ROW_LIMIT = None
    if ROW_LIMIT is not None:
        previous_ROW_LIMIT = self.ROW_LIMIT
        self.ROW_LIMIT = ROW_LIMIT

    try:
        result = self.query_tap(query=query, authenticated=kwargs.get("authenticated", False))
        if count_only:
            return int(list(result[0].values())[0]) if len(result) else 0
        return result
    finally:
        if previous_ROW_LIMIT is not None:
            self.ROW_LIMIT = previous_ROW_LIMIT


def prepare_eso(eso_export, ROW_LIMIT=None, **kwargs):
    """
    Return an Eso instance and ensure query_ancillary exists for older astroquery versions.
    """
    if "row_limit" in kwargs:
        if ROW_LIMIT is not None:
            raise TypeError("Use either ROW_LIMIT or row_limit, not both.")
        ROW_LIMIT = kwargs.pop("row_limit")
    if kwargs:
        unknown_str = ", ".join(sorted(kwargs))
        raise TypeError(f"Unexpected keyword argument(s): {unknown_str}")

    eso_class = eso_export if isinstance(eso_export, type) else type(eso_export)
    if not hasattr(eso_class, "query_ancillary"):
        eso_class.query_ancillary = _query_ancillary_fallback

    eso_instance = eso_export() if isinstance(eso_export, type) else eso_export
    if ROW_LIMIT is not None:
        eso_instance.ROW_LIMIT = ROW_LIMIT
    return eso_instance


def get_oifits_file_info(table, datadir="./data", eso=None, verbose=True):
    """
    Build local file URIs and archive URLs for OIFITS products.

    Parameters
    ----------
    table : astropy.table.Table
        Table containing a 'dp_id' column.
    datadir : str or pathlib.Path, optional
        Directory where OIFITS files are stored.
    eso : astroquery.eso.Eso, optional
        ESO query object, used to construct download URLs.
    verbose : bool, optional
        If True, print the file and URL information.

    Returns
    -------
    oifits_files : list of str
        List of local file URIs (file://...).
    oifits_urls : list of str
        List of corresponding ESO archive URLs (or None if eso not provided).
    """
    datadir = Path(datadir)

    # Build local file URIs
    oifits_files = [
        (datadir / (dp_id + ".fits")).absolute().as_uri()
        for dp_id in table["dp_id"]
    ]

    # Build remote archive URLs (if ESO object provided)
    if eso is not None:
        oifits_urls = [eso.DOWNLOAD_URL + dp_id for dp_id in table["dp_id"]]
    else:
        oifits_urls = [None] * len(oifits_files)

    # Optional printout for quick inspection / SAMP use
    if verbose:
        print("OIFITS files:")
        for file, url in zip(oifits_files, oifits_urls):
            print(f"   File: {file}")
            if url is not None:
                print(f"   URL:  {url}")
            print()

    return oifits_files, oifits_urls


def plot_preview(table_data, table_ancillary):
    """
    Display GRAVITY ancillary preview images for each data product.

    This function loops over a table of GRAVITY data products and, for each
    product, retrieves the associated ancillary preview files (typically two
    images per product). These preview images are displayed side-by-side for
    rapid visual inspection of data quality.

    Parameters
    ----------
    table_data : astropy.table.Table
        Table containing the main GRAVITY data products. Must include at least
        the columns:
            - 'dp_id' : unique dataset identifier
            - 'target_name' : name of the observed target

    table_ancillary : astropy.table.Table
        Table containing ancillary preview products associated with the data.
        Must include:
            - 'product_id' : identifier linking to 'dp_id'
            - 'filenames' : local paths to the preview image files

    Notes
    -----
    - Each product is expected to have exactly two ancillary preview images.
      If this condition is not met, the product is skipped.
    - Images are displayed using matplotlib with axes removed for clarity.
    - The function is intended for interactive use (e.g. in notebooks).

    Returns
    -------
    None
        The function produces plots but does not return any values.
    """

    count = 0
    for row in table_data:

        product_id = row["dp_id"]
        target_name = row["target_name"]

        # select the two ancillary rows belonging to this product
        mask = table_ancillary["product_id"] == product_id
        ancillary_rows = table_ancillary[mask]

        if len(ancillary_rows) != 2:
            print(
                f"Skipping {product_id}: expected 2 ancillary files, "
                f"got {len(ancillary_rows)}"
            )
            continue

        preview_files = []
        for filename in ancillary_rows["filenames"]:
            path = Path(str(filename)).expanduser()
            if not path.exists():
                warnings.warn(
                    f"Skipping missing ancillary preview file for {product_id}: {filename}",
                    stacklevel=2,
                )
                continue
            preview_files.append(path)

        if not preview_files:
            continue

        fig, axes = plt.subplots(1, len(preview_files), figsize=(10 * len(preview_files), 10))
        axes = np.atleast_1d(axes)

        fig.suptitle(
            f"GRAVITY Data Previews – {product_id} – {target_name}",
            fontsize=16,
            fontweight="bold",
            y=0.9,
        )

        for ax, filename in zip(axes, preview_files):
            with Image.open(filename) as img:
                ax.imshow(img.copy())
            ax.axis("off")

        fig.tight_layout(w_pad=0)
        fig.subplots_adjust(wspace=-0.1)

        count += 1
        print(f"Displayed {count} of {len(table_data)} products", end="\r")

    return

def select_calibrators(table, colname="HIERARCH ESO PRO CATG", pattern="CAL"):
    """
    Return only rows classified as calibrators.
    """
    col = table[colname].astype(str)
    mask = np.char.find(col, pattern) >= 0
    return table[mask]


def _dp_id_column(table):
    for colname in ("dp_id", "DP.ID"):
        if colname in table.colnames:
            return colname
    raise KeyError("Expected a product id column named 'dp_id' or 'DP.ID'.")


def _science_dp_ids_from_headers(table_headers):
    """
    Return header DP.ID values not classified as calibrators.
    """
    dp_col = _dp_id_column(table_headers)
    calibrator_ids = set(select_calibrators(table_headers)[dp_col].astype(str))
    return [
        str(dp_id)
        for dp_id in table_headers[dp_col]
        if str(dp_id) not in calibrator_ids
    ]


def _format_dp_id_list(dp_ids):
    if not dp_ids:
        return "  (none)"
    return "\n".join(f"  - {dp_id}" for dp_id in dp_ids)


def _normalize_dp_id_value(dp_id):
    dp_id = str(dp_id).strip()
    if dp_id.lower().endswith(".fits"):
        dp_id = dp_id[:-5]
    return dp_id


def _insmode_parts(insmode):
    return [part.strip().upper() for part in str(insmode).split(",")]


def _is_single_dual_insmode_fallback(science_insmode, calibrator_insmode):
    science_parts = _insmode_parts(science_insmode)
    calibrator_parts = _insmode_parts(calibrator_insmode)
    if len(science_parts) != len(calibrator_parts) or len(science_parts) < 2:
        return False
    if science_parts[1:] != calibrator_parts[1:]:
        return False
    return {science_parts[0], calibrator_parts[0]} == {"SINGLE", "DUAL"}


def select_time_window(table, date_obs, window_hours=6, colname="DATE-OBS"):
    """
    Return rows within ±window_hours of the reference observation time.
    """
    t0 = Time(date_obs)
    t = Time(table[colname])
    dt = (t - t0).to("hour").value
    mask = np.abs(dt) <= window_hours
    return table[mask]


def get_science_and_calibrator(
    *args,
    target=None,
    radius=20 * u.arcsec,
    window_hours=6,
    destination="./data/",
    survey="GRAVITY",
    dp_id=None,
    dp_id_cal=None,
    get_preview=True,
    show_preview=True,
):
    """
    Find a GRAVITY science product for a target, identify a matching calibrator,
    download the selected files, and optionally retrieve/display ancillary
    preview products.

    This function assumes that the archive query returns exactly one science
    product for the target unless `dp_id` is provided. When `dp_id` is provided,
    it is used to select the science product from the target/radius search
    results after checking that the product is not classified as a calibrator.
    The calibrator matching procedure expects exactly one calibrator product
    unless `dp_id_cal` is provided. If either step returns zero or multiple
    matches, a warning is raised and the function exits so that the user can
    refine the selection manually.

    Parameters
    ----------
    target : str
        Target name resolvable by `SkyCoord.from_name`.
    radius : astropy.units.Quantity, optional
        Search radius around the target position.
    window_hours : float, optional
        Allowed time difference between science and calibrator observations.
    destination : str, optional
        Directory where files will be downloaded.
    survey : str, optional
        Survey/collection name to query. Default is "GRAVITY".
    dp_id : str, optional
        Science product id to select from the target/radius query results.
        The product must belong to the target query and must not be classified
        as a calibrator.
    dp_id_cal : str, optional
        Calibrator product id to select when the calibrator matching procedure
        returns multiple candidates. The product must be one of the matched
        calibrator candidates.
    get_preview : bool, optional
        If True, query and download ancillary preview products.
    show_preview : bool, optional
        If True, display preview images. Only used if `get_preview=True`.

    Returns
    -------
    table_target : astropy.table.Table or None
        Selected science product table containing one row, or None if the
        selection was ambiguous.
    table_calibrator : astropy.table.Table or None
        Selected calibrator product table containing one row, or None if the
        selection was ambiguous.
    table_combined : astropy.table.Table or None
        Combined science + calibrator table with local filenames, or None.
    table_ancillary : astropy.table.Table or None
        Associated ancillary preview table with local filenames if requested,
        otherwise None.
    """
    if len(args) > 1 or (args and target is not None):
        raise TypeError(
            "get_science_and_calibrator() now creates its ESO query object "
            "internally. Call it as get_science_and_calibrator(target=..., "
            "radius=..., dp_id=...) without passing eso."
        )
    if args:
        target = args[0]
    if target is None:
        raise TypeError("get_science_and_calibrator() missing required argument: 'target'")
    if not isinstance(target, str):
        raise TypeError(
            "get_science_and_calibrator() now creates its ESO query object "
            "internally. Call it as get_science_and_calibrator(target=..., "
            "radius=..., dp_id=...) without passing eso."
        )

    eso = prepare_eso(Eso)

    # Resolve the target name to sky coordinates
    coords = SkyCoord.from_name(target)
    ra = coords.ra.deg
    dec = coords.dec.deg
    radius_deg = radius.to("deg").value

    # Query science products near the target position
    eso.ROW_LIMIT = None
    table_target = eso.query_surveys(
        survey,
        cone_ra=ra,
        cone_dec=dec,
        cone_radius=radius_deg,
    )

    if len(table_target) == 0:
        warnings.warn(
            f"Expected exactly 1 science product for target '{target}', "
            "but found 0. Please refine the target selection manually."
        )
        return None, None, None, None

    table_target_hrd = eso.get_headers(table_target["dp_id"])
    science_dp_ids = _science_dp_ids_from_headers(table_target_hrd)

    def _print_dp_id_list(dp_ids, title="Science candidate dp_id values"):
        print("\n" + "=" * 80)
        print(f"{title} ({len(dp_ids)}):")
        print("=" * 80)
        print(_format_dp_id_list(dp_ids))
        print("=" * 80 + "\n")

    def _selection_example(param_name, dp_ids):
        if not dp_ids:
            return ""
        return (
            " For example: "
            f'get_science_and_calibrator(target=..., radius=..., {param_name}="{dp_ids[0]}")'
        )

    if dp_id is not None:
        dp_id = _normalize_dp_id_value(dp_id)
        if not dp_id:
            raise ValueError("dp_id must be a non-empty product id string.")
        if dp_id not in set(table_target["dp_id"].astype(str)):
            raise ValueError(
                f"Science product dp_id '{dp_id}' was not found in the "
                f"target/radius query results for '{target}'."
            )
        if dp_id not in science_dp_ids:
            raise ValueError(
                f"Product dp_id '{dp_id}' is classified as a calibrator by "
                "select_calibrators() and cannot be used as the science target."
            )
        table_target = table_target[table_target["dp_id"].astype(str) == dp_id]
        table_target_hrd = table_target_hrd[
            table_target_hrd[_dp_id_column(table_target_hrd)].astype(str) == dp_id
        ]

    elif len(table_target) != 1:
        warnings.warn(
            f"Expected exactly 1 science product for target '{target}', "
            f"but found {len(table_target)}. "
            "Full candidate dp_id list printed below. "
            "Please provide one of these with dp_id=... or refine the target "
            f"selection manually.{_selection_example('dp_id', science_dp_ids)}",
            stacklevel=2,
        )
        sys.stderr.flush()
        sys.stdout.flush()

        _print_dp_id_list(
            science_dp_ids,
            title="Science candidate dp_id values, excluding products classified as calibrators",
        )

        return None, None, None, None

    elif len(science_dp_ids) != 1:
        warnings.warn(
            f"Expected exactly 1 science product for target '{target}', "
            f"but found {len(science_dp_ids)} after excluding products classified "
            "as calibrators by select_calibrators(). "
            "Full candidate dp_id list printed below. "
            "Please provide one of these with dp_id=... or refine the target "
            f"selection manually.{_selection_example('dp_id', science_dp_ids)}",
            stacklevel=2,
        )
        sys.stderr.flush()
        sys.stdout.flush()

        _print_dp_id_list(
            science_dp_ids,
            title="Science candidate dp_id values",
        )

        return None, None, None, None



    proposal_id = table_target["proposal_id"][0]
    obstech = table_target["obstech"][0]
    em_res_power = table_target["em_res_power"][0]
    insmode = table_target_hrd["INSMODE"][0]
    date_obs = table_target_hrd["DATE-OBS"][0]

    # Query possible calibrators with matching observing setup
    column_filters = {
        "proposal_id": f"like '{proposal_id}%'",
        "obstech": obstech,
        "em_res_power": em_res_power,
    }
    table_calibrator = eso.query_surveys(survey, column_filters=column_filters)
    table_calibrator_hrd = eso.get_headers(table_calibrator["dp_id"])

    # Keep only calibrator entries
    table_calibrator_hrd = select_calibrators(table_calibrator_hrd)

    # Restrict to calibrators observed close in time
    table_calibrator_hrd = select_time_window(
        table_calibrator_hrd,
        date_obs,
        window_hours=window_hours,
    )

    exact_insmode = table_calibrator_hrd["INSMODE"].astype(str) == str(insmode)
    compatible_insmode = np.array(
        [
            _is_single_dual_insmode_fallback(insmode, calibrator_insmode)
            for calibrator_insmode in table_calibrator_hrd["INSMODE"]
        ],
        dtype=bool,
    )

    table_calibrator_hrd_exact = table_calibrator_hrd[exact_insmode]
    table_calibrator_hrd_compatible = table_calibrator_hrd[compatible_insmode]

    if dp_id_cal is None:
        if len(table_calibrator_hrd_exact) > 0:
            table_calibrator_hrd = table_calibrator_hrd_exact
        else:
            if len(table_calibrator_hrd_compatible) > 0:
                logger.info(
                    "No exact INSMODE calibrator match for target %r with INSMODE %r; "
                    "using calibrator candidates with compatible SINGLE/DUAL first-component "
                    "mismatch and matching remaining INSMODE components.",
                    target,
                    insmode,
                )
            table_calibrator_hrd = table_calibrator_hrd_compatible
    else:
        table_calibrator_hrd = vstack(
            [table_calibrator_hrd_exact, table_calibrator_hrd_compatible],
            metadata_conflicts="silent",
        )

    calibrator_dp_ids = [
        str(dp_id_candidate)
        for dp_id_candidate in table_calibrator_hrd[_dp_id_column(table_calibrator_hrd)]
    ]
    exact_calibrator_dp_ids = {
        str(dp_id_candidate)
        for dp_id_candidate in table_calibrator_hrd_exact[_dp_id_column(table_calibrator_hrd_exact)]
    }
    compatible_calibrator_dp_ids = {
        str(dp_id_candidate)
        for dp_id_candidate in table_calibrator_hrd_compatible[
            _dp_id_column(table_calibrator_hrd_compatible)
        ]
    }

    if dp_id_cal is not None:
        dp_id_cal = _normalize_dp_id_value(dp_id_cal)
        if not dp_id_cal:
            raise ValueError("dp_id_cal must be a non-empty product id string.")
        if dp_id_cal not in calibrator_dp_ids:
            raise ValueError(
                f"Calibrator product dp_id_cal '{dp_id_cal}' was not found "
                "among the matched calibrator candidates for this science "
                f"target. Candidate calibrator dp_id values:\n"
                f"{_format_dp_id_list(calibrator_dp_ids)}"
            )
        if dp_id_cal in compatible_calibrator_dp_ids and dp_id_cal not in exact_calibrator_dp_ids:
            logger.info(
                "Using explicitly selected calibrator %r with compatible SINGLE/DUAL "
                "first-component INSMODE mismatch for target %r.",
                dp_id_cal,
                target,
            )
        table_calibrator_hrd = table_calibrator_hrd[
            table_calibrator_hrd[_dp_id_column(table_calibrator_hrd)].astype(str)
            == dp_id_cal
        ]

    elif len(table_calibrator_hrd) != 1:
        warnings.warn(
            f"Expected exactly 1 matching calibrator for target '{target}', "
            f"but found {len(table_calibrator_hrd)}. "
            "Full candidate dp_id list printed below. "
            "Please provide one of these with dp_id_cal=... or refine the "
            f"calibrator selection manually.{_selection_example('dp_id_cal', calibrator_dp_ids)}",
            stacklevel=2,
        )
        sys.stderr.flush()
        sys.stdout.flush()

        _print_dp_id_list(
            calibrator_dp_ids,
            title="Calibrator candidate dp_id values",
        )

        return table_target, None, None, None

    # Keep only the matched calibrator product
    table_calibrator = table_calibrator[
        table_calibrator["dp_id"].astype(str)
        == str(table_calibrator_hrd[_dp_id_column(table_calibrator_hrd)][0])
    ]

    if len(table_calibrator) != 1:
        warnings.warn(
            f"Expected exactly 1 calibrator product after matching, "
            f"but found {len(table_calibrator)}. "
            "Please refine the calibrator selection manually."
        )
        return table_target, None, None, None

    # Combine science and calibrator products and download them
    table_combined = vstack([table_target, table_calibrator])
    table_combined["filenames"] = eso.retrieve_data(
        table_combined["dp_id"],
        destination=destination,
    )

    table_ancillary = None

    # Optionally query and download ancillary preview products
    if get_preview:
        table_ancillary = eso.query_ancillary(
            table_combined["dp_id"],
            column_filters={"eso_category": "ANCILLARY.PREVIEW"},
        )
        table_ancillary["filenames"] = eso.retrieve_data(
            table_ancillary["archive_id"],
            destination=destination,
        )

        # Optionally display the preview images
        if show_preview:
            plot_preview(table_combined, table_ancillary)

    return table_target, table_calibrator, table_combined, table_ancillary


from pathlib import Path
import warnings

def write_viscal_sof(
    table_target,
    table_calibrator,
    datadir="./data",
    diameter_cat="M.GRAVITY.2020-06-10T12:25:17.246.fits",
    filename="viscal.sof",
):
    """
    Create a viscal.sof file for GRAVITY `gravity_viscal`.

    Parameters
    ----------
    table_target : astropy.table.Table
        Table containing the science product (expects 1 row).
    table_calibrator : astropy.table.Table
        Table containing the calibrator product (expects 1 row).
    datadir : str or pathlib.Path, optional
        Directory where the FITS files are located.
    diameter_cat : str, optional
        Filename of the diameter catalog (e.g. 'M.GRAVITY....fits').
        If provided, it will be included as DIAMETER_CAT.
    filename : str, optional
        Name of the SOF file to write.

    Returns
    -------
    sof_path : pathlib.Path
        Path to the written SOF file.
    """
    datadir = Path(datadir)
    sof_path = datadir / filename

    # --- sanity checks ---
    if len(table_target) != 1:
        warnings.warn(f"Expected 1 science file, got {len(table_target)}")
    if len(table_calibrator) != 1:
        warnings.warn(f"Expected 1 calibrator file, got {len(table_calibrator)}")

    sci_id = table_target["dp_id"][0]
    cal_id = table_calibrator["dp_id"][0]

    sci_file = f"{sci_id}.fits"
    cal_file = f"{cal_id}.fits"

    lines = [
        f"{sci_file}  SINGLE_SCI_VIS",
        f"{cal_file}  SINGLE_CAL_VIS",
    ]

    if diameter_cat is not None:
        lines.append(f"{diameter_cat}  DIAMETER_CAT")

    # --- write file ---
    with open(sof_path, "w") as f:
        for line in lines:
            f.write(line + "\n")

    print(f"Wrote SOF file: {sof_path}")
    return sof_path

import subprocess
from pathlib import Path


def run_gravity_viscal(
    sof_file="viscal.sof",
    datadir="./data",
    esorex_path="/opt/local/bin/esorex",
    force_calib=True,
    verbose=True,
):
    """
    Run the ESO GRAVITY calibration pipeline (`gravity_viscal`) on a given SOF file.

    This function wraps the `esorex gravity_viscal` command and executes it
    within a specified working directory. It constructs the appropriate command,
    optionally includes calibration flags, and captures the pipeline output.

    Parameters
    ----------
    sof_file : str, optional
        Name of the SOF file describing the input data (default: "viscal.sof").
    datadir : str or pathlib.Path, optional
        Directory containing the SOF file and input FITS products. The pipeline
        is executed in this directory (default: "./data").
    esorex_path : str, optional
        Full path to the `esorex` executable (default: "/opt/local/bin/esorex").
        This should match the path returned by `which esorex`.
    force_calib : bool, optional
        If True, include the `--force-calib=true` option to force recalibration
        even if existing calibration products are present (default: True).
    verbose : bool, optional
        If True, print the executed command and display STDOUT/STDERR from the
        pipeline (default: True).

    Returns
    -------
    subprocess.CompletedProcess
        Result object containing the command execution details, including
        stdout, stderr, and return code.

    Raises
    ------
    RuntimeError
        If the pipeline execution fails (i.e. returns a non-zero exit code).

    Notes
    -----
    This is equivalent to running the following command in a terminal:

        esorex gravity_viscal --force-calib=true viscal.sof

    The calibrated OIFITS products are written to the working directory.
    """
    datadir = Path(datadir)

    cmd = [esorex_path, "gravity_viscal"]

    if force_calib:
        cmd.append("--force-calib=true")

    cmd.append(sof_file)

    if verbose:
        print("Running:", " ".join(cmd))
        print(f"Working directory: {datadir.resolve()}")

    result = subprocess.run(
        cmd,
        cwd=datadir,
        capture_output=True,
        text=True,
    )

    if verbose:
        print("\n--- STDOUT ---")
        print(result.stdout)
        print("\n--- STDERR ---")
        print(result.stderr)

    if result.returncode != 0:
        raise RuntimeError("gravity_viscal failed")

    return result


from astropy.samp import SAMPIntegratedClient
client = SAMPIntegratedClient()

def sendOiFitsWithSAMP(filenames):
    """
    Send one or more OIFITS file URLs through SAMP.

    Parameters
    ----------
    filenames : str or iterable of str
        A single file/URL string or a list of file/URL strings to send with
        the ``table.load.fits`` SAMP message type.
    """
    if isinstance(filenames, str):
        filenames = [filenames]

    try:
        # Always reset the connection cleanly
        try:
            if client.is_connected:
                client.disconnect()
        except Exception:
            pass
        client.connect()
            
        for url in filenames:
            message = {"samp.mtype": "table.load.fits", "samp.params": {"url": url}}
            receivers = [client.get_metadata(id)["samp.name"] for id in client.notify_all(message)]
            print(f"'{url}' sent to {', '.join(receivers)}")
    except Exception:
        print("Error trying to send a SAMP message.")
        print("Please check that you are running a VO compliant application (with table.load.fits support).")
        print("You can try :")
        print(" - OIFitsExplorer ( https://www.jmmc.fr/oifitsexplorer ) ")
        print(" - OImaging       ( https://www.jmmc.fr/oimaging ) - only use the last submitted oifits")
        print(" - LITpro         ( https://www.jmmc.fr/litpro ) ")
