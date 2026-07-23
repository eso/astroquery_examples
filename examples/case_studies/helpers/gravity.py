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

    table_ancillary.sort("original_filename") # make sure that preview files are always in the same order (e.g. preview1, preview2) for consistent display

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


def _format_calibrator_dp_id_list(table, science_insmode, warning_ids):
    if len(table) == 0:
        return "  (none)"

    dp_col = _dp_id_column(table)
    lines = []
    for row in table:
        dp_id = str(row[dp_col])
        line = f"  - {dp_id}"
        if dp_id in warning_ids:
            calibrator_field_mode = _insmode_parts(row["INSMODE"])[0]
            science_field_mode = _insmode_parts(science_insmode)[0]
            note = (
                "calibrator/science in "
                f"{calibrator_field_mode}/{science_field_mode} "
                "field mode mismatch"
            )
            line += f" --> \033[33m{note}\033[0m"
        lines.append(line)
    return "\n".join(lines)


def _normalize_dp_id_value(dp_id):
    dp_id = str(dp_id).strip()
    if dp_id.lower().endswith(".fits"):
        dp_id = dp_id[:-5]
    return dp_id


def _insmode_parts(insmode):
    return [part.strip().upper() for part in str(insmode).split(",")]


def _is_dual_science_single_calibrator_fallback(science_insmode, calibrator_insmode):
    science_parts = _insmode_parts(science_insmode)
    calibrator_parts = _insmode_parts(calibrator_insmode)
    if len(science_parts) != len(calibrator_parts) or len(science_parts) < 2:
        return False
    if science_parts[1:] != calibrator_parts[1:]:
        return False
    return science_parts[0] == "DUAL" and calibrator_parts[0] == "SINGLE"


def _is_single_science_dual_calibrator_mismatch(science_insmode, calibrator_insmode):
    science_parts = _insmode_parts(science_insmode)
    calibrator_parts = _insmode_parts(calibrator_insmode)
    if len(science_parts) != len(calibrator_parts) or len(science_parts) < 2:
        return False
    if science_parts[1:] != calibrator_parts[1:]:
        return False
    return science_parts[0] == "SINGLE" and calibrator_parts[0] == "DUAL"


def select_time_window(table, date_obs, window_hours=6, colname="DATE-OBS"):
    """
    Return rows within ±window_hours of the reference observation time.
    """
    t0 = Time(date_obs)
    t = Time(table[colname])
    dt = (t - t0).to("hour").value
    mask = np.abs(dt) <= window_hours
    return table[mask]


def _closest_time_row(table, date_obs, colname="DATE-OBS"):
    t0 = Time(date_obs)
    t = Time(table[colname])
    dt = np.abs((t - t0).to("hour").value)
    return table[np.argmin(dt):np.argmin(dt) + 1]


def _row_colnames(row):
    if hasattr(row, "colnames"):
        return row.colnames
    table = getattr(row, "table", None)
    return getattr(table, "colnames", [])


def _field_mode_from_insmode(insmode):
    parts = _insmode_parts(insmode)
    if parts and parts[0] in {"SINGLE", "DUAL"}:
        return parts[0]
    return None


def get_calibrator(
    dp_id,
    window_hours=6,
    destination="./data/",
    survey="GRAVITY",
    dp_id_cal=None,
):
    """
    Find matching GRAVITY calibrator products for one or more science products.

    Parameters
    ----------
    dp_id : str or iterable
        Science product id, or product ids, to use as the starting point. Values
        may be strings, comma-separated strings, table columns, or other
        iterables. A trailing ".fits" suffix is accepted and stripped.
    window_hours : float, optional
        Allowed time difference between science and calibrator observations.
    destination : str, optional
        Retained for compatibility with older notebook calls. This function no
        longer downloads data.
    survey : str, optional
        Survey/collection name to query. Default is "GRAVITY".
    dp_id_cal : str or iterable, optional
        Known calibrator product id, or ids, to select from the matched
        calibrator candidates.

    Returns
    -------
    table_calibrator : astropy.table.Table or None
        Matching calibrator product rows, or None if no calibrator rows were
        selected.
    """
    del destination

    science_dp_ids = [
        _normalize_dp_id_value(value)
        for value in _normalize_product_ids(dp_id)
    ]
    science_dp_ids = [value for value in science_dp_ids if value]
    if not science_dp_ids:
        raise ValueError("dp_id must contain at least one science product id.")

    requested_calibrator_ids = {
        _normalize_dp_id_value(value)
        for value in _normalize_product_ids(dp_id_cal)
    }
    requested_calibrator_ids = {
        value for value in requested_calibrator_ids if value
    }

    def _print_dp_id_list(dp_ids, title, formatted_lines=None):
        print("\n" + "=" * 80)
        print(f"{title} ({len(dp_ids)}):")
        print("=" * 80)
        print(formatted_lines or _format_dp_id_list(dp_ids))
        print("=" * 80 + "\n")

    def _selection_example(param_name, dp_ids):
        if not dp_ids:
            return ""
        return (
            " For example: "
            f'get_calibrator(dp_id=..., {param_name}="{dp_ids[0]}")'
        )

    eso = prepare_eso(Eso)
    eso.ROW_LIMIT = None

    table_science_headers = eso.get_headers(science_dp_ids)
    science_header_ids = set(_science_dp_ids_from_headers(table_science_headers))
    calibrator_like_inputs = [
        value for value in science_dp_ids if value not in science_header_ids
    ]
    if calibrator_like_inputs:
        warnings.warn(
            "Ignoring dp_id values classified as calibrators by "
            f"select_calibrators(): {', '.join(calibrator_like_inputs)}",
            stacklevel=2,
        )

    table_calibrators = []

    for index, science_dp_id in enumerate(science_dp_ids, start=1):
        print(f"Processing science dp_id {index}/{len(science_dp_ids)}: {science_dp_id}")

        if science_dp_id not in science_header_ids:
            continue

        table_science = eso.query_surveys(
            survey,
            column_filters={"dp_id": science_dp_id},
        )
        if len(table_science) != 1:
            warnings.warn(
                f"Expected exactly 1 science product for dp_id '{science_dp_id}', "
                f"but found {len(table_science)}. Skipping.",
                stacklevel=2,
            )
            continue

        science_header = table_science_headers[
            table_science_headers[_dp_id_column(table_science_headers)].astype(str)
            == science_dp_id
        ]
        if len(science_header) != 1:
            warnings.warn(
                f"Expected exactly 1 science header for dp_id '{science_dp_id}', "
                f"but found {len(science_header)}. Skipping.",
                stacklevel=2,
            )
            continue

        proposal_id = table_science["proposal_id"][0]
        obstech = table_science["obstech"][0]
        em_res_power = table_science["em_res_power"][0]
        insmode = science_header["INSMODE"][0]
        date_obs = science_header["DATE-OBS"][0]

        column_filters = {
            "proposal_id": f"like '{proposal_id}%'",
            "obstech": obstech,
            "em_res_power": em_res_power,
        }
        table_calibrator = eso.query_surveys(survey, column_filters=column_filters)
        table_calibrator_hrd = eso.get_headers(table_calibrator["dp_id"])
        table_calibrator_hrd = select_calibrators(table_calibrator_hrd)
        table_calibrator_hrd = select_time_window(
            table_calibrator_hrd,
            date_obs,
            window_hours=window_hours,
        )

        exact_insmode = table_calibrator_hrd["INSMODE"].astype(str) == str(insmode)
        dual_science_single_calibrator = np.array(
            [
                _is_dual_science_single_calibrator_fallback(
                    insmode,
                    calibrator_insmode,
                )
                for calibrator_insmode in table_calibrator_hrd["INSMODE"]
            ],
            dtype=bool,
        )
        single_science_dual_calibrator = np.array(
            [
                _is_single_science_dual_calibrator_mismatch(
                    insmode,
                    calibrator_insmode,
                )
                for calibrator_insmode in table_calibrator_hrd["INSMODE"]
            ],
            dtype=bool,
        )
        table_calibrator_hrd_exact = table_calibrator_hrd[exact_insmode]
        table_calibrator_hrd_compatible = table_calibrator_hrd[
            dual_science_single_calibrator
        ]
        table_calibrator_hrd_rejected = table_calibrator_hrd[
            single_science_dual_calibrator
        ]

        display_calibrator_hrd = vstack(
            [
                table_calibrator_hrd_exact,
                table_calibrator_hrd_compatible,
                table_calibrator_hrd_rejected,
            ],
            metadata_conflicts="silent",
        )
        display_calibrator_dp_ids = [
            str(value)
            for value in display_calibrator_hrd[_dp_id_column(display_calibrator_hrd)]
        ]
        compatible_calibrator_dp_ids = {
            str(value)
            for value in table_calibrator_hrd_compatible[
                _dp_id_column(table_calibrator_hrd_compatible)
            ]
        }
        exact_calibrator_dp_ids = {
            str(value)
            for value in table_calibrator_hrd_exact[
                _dp_id_column(table_calibrator_hrd_exact)
            ]
        }
        rejected_calibrator_dp_ids = {
            str(value)
            for value in table_calibrator_hrd_rejected[
                _dp_id_column(table_calibrator_hrd_rejected)
            ]
        }
        formatted_display_calibrator_dp_ids = _format_calibrator_dp_id_list(
            display_calibrator_hrd,
            science_insmode=insmode,
            warning_ids=rejected_calibrator_dp_ids,
        )

        automatically_allowed_calibrator_hrd = vstack(
            [table_calibrator_hrd_exact, table_calibrator_hrd_compatible],
            metadata_conflicts="silent",
        )

        if requested_calibrator_ids:
            table_calibrator_hrd = vstack(
                [
                    table_calibrator_hrd_exact,
                    table_calibrator_hrd_compatible,
                    table_calibrator_hrd_rejected,
                ],
                metadata_conflicts="silent",
            )
        else:
            table_calibrator_hrd = automatically_allowed_calibrator_hrd

        calibrator_dp_ids = [
            str(value)
            for value in table_calibrator_hrd[_dp_id_column(table_calibrator_hrd)]
        ]

        if requested_calibrator_ids:
            selected_calibrator_ids = [
                value for value in calibrator_dp_ids
                if value in requested_calibrator_ids
            ]
            if not selected_calibrator_ids:
                warnings.warn(
                    f"None of dp_id_cal={sorted(requested_calibrator_ids)} matched "
                    f"calibrator candidates for science dp_id '{science_dp_id}'.",
                    stacklevel=2,
                )
                _print_dp_id_list(
                    display_calibrator_dp_ids,
                    title=f"Calibrator candidate dp_id values for {science_dp_id}",
                    formatted_lines=formatted_display_calibrator_dp_ids,
                )
                continue

            for value in selected_calibrator_ids:
                if value in compatible_calibrator_dp_ids and value not in exact_calibrator_dp_ids:
                    logger.info(
                        "Using explicitly selected calibrator %r with science "
                        "DUAL and calibrator SINGLE field mode for science "
                        "dp_id %r.",
                        value,
                        science_dp_id,
                    )

                if value in rejected_calibrator_dp_ids:
                    warnings.warn(
                        f"Explicitly selected calibrator '{value}' has a "
                        "calibrator/science DUAL/SINGLE field mode mismatch "
                        f"for science dp_id '{science_dp_id}'.",
                        stacklevel=2,
                    )

            table_calibrator_hrd = table_calibrator_hrd[
                np.isin(
                    table_calibrator_hrd[_dp_id_column(table_calibrator_hrd)].astype(str),
                    selected_calibrator_ids,
                )
            ]
        elif len(table_calibrator_hrd) == 0:
            warnings.warn(
                f"Expected exactly 1 matching calibrator for science dp_id "
                f"'{science_dp_id}', but found 0. "
                "Full candidate dp_id list printed below. "
                "Please provide one of these with dp_id_cal=... or refine the "
                "selection manually."
                f"{_selection_example('dp_id_cal', display_calibrator_dp_ids)}",
                stacklevel=2,
            )
            sys.stderr.flush()
            sys.stdout.flush()
            _print_dp_id_list(
                display_calibrator_dp_ids,
                title=f"Calibrator candidate dp_id values for {science_dp_id}",
                formatted_lines=formatted_display_calibrator_dp_ids,
            )
            continue

        elif len(table_calibrator_hrd) > 1:
            table_calibrator_hrd = _closest_time_row(table_calibrator_hrd, date_obs)
            closest_calibrator_id = str(
                table_calibrator_hrd[_dp_id_column(table_calibrator_hrd)][0]
            )
            warnings.warn(
                f"Expected exactly 1 matching calibrator for science dp_id "
                f"'{science_dp_id}', but found {len(calibrator_dp_ids)}. "
                "Full candidate dp_id list printed below. "
                f"Automatically selected closest-in-time calibrator '{closest_calibrator_id}'. "
                "Provide dp_id_cal=... to override this selection.",
                stacklevel=2,
            )
            sys.stderr.flush()
            sys.stdout.flush()
            _print_dp_id_list(
                display_calibrator_dp_ids,
                title=f"Calibrator candidate dp_id values for {science_dp_id}",
                formatted_lines=formatted_display_calibrator_dp_ids,
            )

        selected_header_ids = {
            str(value)
            for value in table_calibrator_hrd[_dp_id_column(table_calibrator_hrd)]
        }
        table_selected_calibrators = table_calibrator[
            np.isin(table_calibrator["dp_id"].astype(str), list(selected_header_ids))
        ]
        if len(table_selected_calibrators) != len(selected_header_ids):
            warnings.warn(
                f"Expected {len(selected_header_ids)} calibrator product row(s) "
                f"after matching science dp_id '{science_dp_id}', but found "
                f"{len(table_selected_calibrators)}. Skipping.",
                stacklevel=2,
            )
            continue

        table_calibrators.append(table_selected_calibrators)

    if not table_calibrators:
        return None
    return vstack(table_calibrators, metadata_conflicts="silent")


from pathlib import Path
import warnings

def write_viscal_sof(
    table_target,
    table_calibrator,
    datadir="./data",
    diameter_cat="M.GRAVITY.2020-06-10T12:25:17.246.fits",
    filename=None,
):
    """
    Create a viscal.sof file for GRAVITY `gravity_viscal`.

    Parameters
    ----------
    table_target : astropy.table.Table
        Table containing one or more science products.
    table_calibrator : astropy.table.Table
        Table containing one or more calibrator products. Rows are paired with
        science rows by order.
    datadir : str or pathlib.Path, optional
        Directory where the FITS files are located.
    diameter_cat : str, optional
        Filename of the diameter catalog (e.g. 'M.GRAVITY....fits').
        If provided, it will be included as DIAMETER_CAT.
    filename : str, optional
        Name of the SOF file to write. If omitted, files are named
        ``viscal_{dp_id}.sof`` using the science product id. This argument is
        only valid when writing a single SOF file.

    Notes
    -----
    The SOF science/calibrator tags are derived from the first field of
    ``INSMODE`` when available. If the input tables do not include ``INSMODE``,
    the helper queries the ESO product headers for the needed product ids.

    Returns
    -------
    sof_path : pathlib.Path or list[pathlib.Path]
        Path to the written SOF file, or paths when multiple science/calibrator
        pairs are provided.
    """
    datadir = Path(datadir)

    if len(table_target) != len(table_calibrator):
        raise ValueError(
            "table_target and table_calibrator must contain the same number "
            f"of rows; got {len(table_target)} science and "
            f"{len(table_calibrator)} calibrator rows."
        )
    if len(table_target) == 0:
        raise ValueError("table_target and table_calibrator must not be empty.")
    if filename is not None and len(table_target) != 1:
        raise ValueError("filename can only be used when writing one SOF file.")

    sof_paths = []
    eso = None
    field_mode_cache = {}

    def _field_mode_for_row(row, dp_id):
        nonlocal eso

        for colname in ("INSMODE", "insmode"):
            if colname in _row_colnames(row):
                field_mode = _field_mode_from_insmode(row[colname])
                if field_mode is not None:
                    return field_mode

        if dp_id not in field_mode_cache:
            if eso is None:
                eso = prepare_eso(Eso)
            header = eso.get_headers([dp_id])
            field_mode = None
            if len(header) == 1 and "INSMODE" in header.colnames:
                field_mode = _field_mode_from_insmode(header["INSMODE"][0])
            if field_mode is None:
                warnings.warn(
                    f"Could not determine INSMODE field mode for dp_id '{dp_id}'. "
                    "Using SINGLE in the SOF tag.",
                    stacklevel=2,
                )
                field_mode = "SINGLE"
            field_mode_cache[dp_id] = field_mode

        return field_mode_cache[dp_id]

    for target_row, calibrator_row in zip(table_target, table_calibrator):
        sci_id = _normalize_dp_id_value(target_row["dp_id"])
        cal_id = _normalize_dp_id_value(calibrator_row["dp_id"])
        sci_field_mode = _field_mode_for_row(target_row, sci_id)
        cal_field_mode = _field_mode_for_row(calibrator_row, cal_id)
        if sci_field_mode == "SINGLE" and cal_field_mode == "DUAL":
            warnings.warn(
                "Writing SOF with calibrator/science in DUAL/SINGLE "
                f"field mode mismatch for science dp_id '{sci_id}' and "
                f"calibrator dp_id '{cal_id}'.",
                stacklevel=2,
            )

        sof_filename = filename or f"viscal_{sci_id}.sof"
        sof_path = datadir / sof_filename

        sci_file = f"{sci_id}.fits"
        cal_file = f"{cal_id}.fits"

        lines = [
            f"{sci_file}  {sci_field_mode}_SCI_VIS",
            f"{cal_file}  {cal_field_mode}_CAL_VIS",
        ]

        if diameter_cat is not None:
            lines.append(f"{diameter_cat}  DIAMETER_CAT")

        with open(sof_path, "w") as f:
            for line in lines:
                f.write(line + "\n")

        print(f"Wrote SOF file: {sof_path}")
        sof_paths.append(sof_path)

    return sof_paths[0] if len(sof_paths) == 1 else sof_paths

import subprocess
from pathlib import Path


def run_gravity_viscal(
    dp_id=None,
    sof_file=None,
    datadir="./data",
    esorex_path="/opt/local/bin/esorex",
    force_calib=True,
    verbose=True,
):
    """
    Run the ESO GRAVITY calibration pipeline (`gravity_viscal`) on SOF files.

    This function wraps the `esorex gravity_viscal` command and executes it
    within a specified working directory. It constructs the appropriate command,
    optionally includes calibration flags, and captures the pipeline output.

    Parameters
    ----------
    dp_id : str, astropy.table.Table, or iterable, optional
        Science product id(s), or a table containing a ``dp_id`` column. Used to
        infer SOF names of the form ``viscal_{dp_id}.sof``.
    sof_file : str or iterable, optional
        Explicit SOF file name(s). If omitted, ``dp_id`` is required.
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
    subprocess.CompletedProcess or list[subprocess.CompletedProcess]
        Result object(s) containing command execution details.

    Raises
    ------
    RuntimeError
        If the pipeline execution fails (i.e. returns a non-zero exit code).

    Notes
    -----
    This is equivalent to running the following command in a terminal:

        esorex gravity_viscal --force-calib=true viscal_{dp_id}.sof

    The calibrated OIFITS products are written to the working directory.
    """
    datadir = Path(datadir)
    if sof_file is None:
        if dp_id is None:
            raise ValueError("Provide dp_id or sof_file.")
        if hasattr(dp_id, "colnames") and "dp_id" in dp_id.colnames:
            dp_ids = [_normalize_dp_id_value(value) for value in dp_id["dp_id"]]
        else:
            dp_ids = [
                _normalize_dp_id_value(value)
                for value in _normalize_product_ids(dp_id)
            ]
        sof_files = [f"viscal_{value}.sof" for value in dp_ids if value]
    else:
        sof_files = _normalize_product_ids(sof_file)

    if not sof_files:
        raise ValueError("No SOF files to run.")

    results = []
    for current_sof_file in sof_files:
        cmd = [esorex_path, "gravity_viscal"]

        if force_calib:
            cmd.append("--force-calib=true")

        cmd.append(current_sof_file)

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
            raise RuntimeError(f"gravity_viscal failed for {current_sof_file}")

        results.append(result)

    return results[0] if len(results) == 1 else results


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


def summarize_public(table, use_color=True):
    now = Time.now()

    date_col = table["obs_release_date"]
    dp_ids = table["dp_id"]

    # Convert MaskedColumn/object column safely to plain string array
    dates = np.array(date_col.filled("2100-01-01T00:00:00Z"), dtype=str)

    release = Time(dates, format="isot", scale="utc")
    is_public = release < now

    n_public = int(np.sum(is_public))
    n_total = len(table)

    print(f"Public: {n_public}/{n_total} | Restricted: {n_total - n_public}/{n_total}\n")

    for dp, pub, date in zip(dp_ids, is_public, dates):
        if pub:
            status = "public"
            if use_color:
                status = f"\033[92m{status}\033[0m"
        else:
            status = f"restricted (until {date.split('Z')[0]})"
            if use_color:
                status = f"\033[91m{status}\033[0m"

        print(f"{dp} --> {status}")

    if n_public == n_total:
        print("\nAll data products are public.")
    elif n_public == 0:
        print("\nNo data products are public and require authentication.")
    elif n_public < n_total:
        print(f"\n{n_total - n_public} data products are not public and require authentication.")
