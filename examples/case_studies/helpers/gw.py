from __future__ import annotations

import json
import webbrowser
from pathlib import Path
from urllib.parse import urlencode

import astropy.coordinates as coord
import astropy.units as u
import numpy as np
import requests
from astropy.io import fits
from astropy.time import Time
from astropy import wcs
from matplotlib import pyplot as plt


def _require_dependency(import_path: str, package_name: str):
    try:
        module = __import__(import_path, fromlist=[import_path.split(".")[-1]])
    except ImportError as exc:
        raise ImportError(
            f"Optional dependency '{package_name}' is required for this workflow. "
            f"Install it with `pip install {package_name}`."
        ) from exc
    return module


def _optional_spherical_polygon():
    """Try to import a spherical-polygon implementation for robust orientation fixes."""
    try:
        from spherical_geometry.polygon import SphericalPolygon  # type: ignore
        return SphericalPolygon
    except ImportError:
        pass

    try:
        from ESOAsg.ancillary.polygons import SphericalPolygon  # type: ignore
        return SphericalPolygon
    except ImportError:
        return None


def download_gw_bayestar(superevent_name: str, output_dir: str | Path = "./data",
                         file_name: str = "bayestar.fits.gz") -> Path:
    """Download the BAYESTAR skymap for a GraceDB superevent."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"{superevent_name}_bayestar.fits.gz"
    if output_path.exists():
        return output_path

    url = f"https://gracedb.ligo.org/apiweb/superevents/{superevent_name}/files/{file_name}"
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    output_path.write_bytes(response.content)
    return output_path


def _unwrap_ra(ra_deg: np.ndarray) -> np.ndarray:
    return np.rad2deg(np.unwrap(np.deg2rad(ra_deg), discont=np.pi))


def _continuous_contour_vertices(contour: list[list[float]] | np.ndarray) -> np.ndarray:
    """
    Represent a contour with continuous RA values to avoid artificial 0/360 jumps.

    TAP polygon parsing is sensitive to long apparent edges. If a contour crosses
    RA=0, writing raw wrapped coordinates such as 359 -> 1 can make the polygon
    appear to span almost the whole sky. Here we unwrap the longitudes first.
    """
    contour_array = np.asarray(contour, dtype=float)
    if len(contour_array) == 0:
        return contour_array

    contour_array = contour_array.copy()
    contour_array[:, 0] = _unwrap_ra(contour_array[:, 0])

    # Rotate so the sequence starts at the smallest continuous RA. This keeps
    # the polygon representation stable and easier to inspect.
    start_idx = int(np.argmin(contour_array[:, 0]))
    if start_idx:
        contour_array = np.vstack([contour_array[start_idx:], contour_array[:start_idx]])

    return contour_array


def _ensure_counterclockwise(contour: list[list[float]]) -> list[list[float]]:
    """
    Ensure the polygon is counterclockwise.

    We first try a proper spherical-polygon implementation, which matches the
    old ESOAsg behaviour. If that is unavailable, we fall back to a local
    projection test on continuous (unwrapped) RA values.
    """
    contour_array = _continuous_contour_vertices(contour)
    if len(contour_array) < 3:
        return contour_array.tolist()

    spherical_polygon_cls = _optional_spherical_polygon()
    if spherical_polygon_cls is not None:
        spherical_polygon = spherical_polygon_cls.from_lonlat(
            contour_array[:, 0], contour_array[:, 1], degrees=True
        )

        contour_oriented = []
        for lon, lat in spherical_polygon.to_lonlat():
            for ra, dec in zip(lon, lat):
                contour_oriented.append([float(ra), float(dec)])

        contour_array = _continuous_contour_vertices(contour_oriented)
        if len(contour_array) >= 2 and np.allclose(contour_array[0], contour_array[-1]):
            contour_array = contour_array[:-1]

    ra = contour_array[:, 0]
    dec = contour_array[:, 1]

    x1 = ra
    y1 = dec
    x2 = np.roll(ra, -1)
    y2 = np.roll(dec, -1)
    signed_area = 0.5 * np.sum(x1 * y2 - x2 * y1)

    # In archive polygon queries, the interior is sensitive to orientation.
    # Empirically, for RA/Dec vertex lists written in the usual numerical
    # ordering, a positive planar signed area corresponds to the complement
    # region on the sphere, so we reverse that case here.
    if signed_area > 0:
        contour_array = contour_array[::-1]
    return contour_array.tolist()


def contours_from_gw(file_name: str | Path, credible_level: float = 50.0):
    """Extract probability contours from a skymap file."""
    ligo_contour = _require_dependency(
        "ligo.skymap.tool.ligo_skymap_contour", "ligo.skymap"
    )

    file_name = str(file_name)
    contour_tmp_file = f"{file_name}.tmp.json"
    contour_path = Path(contour_tmp_file)
    if contour_path.exists():
        contour_path.unlink()

    ligo_contour.main(
        args=[file_name, "--output", contour_tmp_file, "--contour", str(credible_level)]
    )

    contours_dict = json.loads(contour_path.read_text())
    contour_path.unlink(missing_ok=True)

    contours = contours_dict["features"][0]["geometry"]["coordinates"]
    return [_ensure_counterclockwise(contour) for contour in contours]


def _default_mw_image_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "MW_edgeon_edr3_unannotate.jpg"


def _normalise_levels(levels) -> list[float]:
    levels = [float(level) for level in levels]
    if not levels:
        raise ValueError("At least one credible level is required.")
    if any(level <= 0 or level >= 100 for level in levels):
        raise ValueError("Credible levels must be between 0 and 100.")
    return sorted(levels)


def _credible_level_map(probability: np.ndarray) -> np.ndarray:
    probability = np.asarray(probability, dtype=float)
    probability = np.where(np.isfinite(probability) & (probability > 0), probability, 0.0)

    probability_sum = probability.sum()
    if probability_sum <= 0:
        raise ValueError("The gravitational-wave map contains no positive probability.")

    probability = probability / probability_sum
    pixel_order = np.argsort(probability)[::-1]
    cumulative_probability = np.cumsum(probability[pixel_order]) * 100.0

    credible_level = np.empty_like(probability)
    credible_level[pixel_order] = cumulative_probability
    return credible_level


def _gw_confidence_grid(file_name: str | Path, *, grid_shape: tuple[int, int] = (360, 720)):
    healpy = _require_dependency("healpy", "healpy")

    n_lat, n_lon = grid_shape
    if n_lat < 2 or n_lon < 2:
        raise ValueError("grid_shape must contain at least two latitude and longitude samples.")

    map_data, map_header = healpy.read_map(
        str(file_name), field=0, h=True, dtype=float, nest=False
    )
    map_header = dict(map_header)
    confidence = _credible_level_map(map_data)

    x_galactic = np.linspace(-180.0, 180.0, n_lon)
    y_galactic = np.linspace(-90.0, 90.0, n_lat)
    x_grid, y_grid = np.meshgrid(x_galactic, y_galactic)

    galactic_coordinates = coord.SkyCoord(
        l=(-x_grid.ravel()) * u.deg,
        b=y_grid.ravel() * u.deg,
        frame="galactic",
    )
    icrs_coordinates = galactic_coordinates.icrs

    nside = healpy.npix2nside(len(confidence))
    theta = np.deg2rad(90.0 - icrs_coordinates.dec.deg)
    phi = np.deg2rad(icrs_coordinates.ra.deg)
    pixels = healpy.ang2pix(nside, theta, phi, nest=False)

    return x_galactic, y_galactic, confidence[pixels].reshape(n_lat, n_lon), map_header


def show_contours_from_gw(file_name: str | Path, *, levels=(5, 25, 50),
                          mw_image: str | Path | None = None, colors=None,
                          fill_alpha: float = 0.5, line_alpha: float = 1.0,
                          linewidth: float = 1,
                          grid_shape: tuple[int, int] = (360, 720),
                          figsize: tuple[float, float] = (12.0, 6.0),
                          save_figure: str | Path | None = None,
                          return_fig: bool = False):
    """
    Show GW credible-level contours on the Gaia/EDR3 edge-on Milky Way image.

    Parameters
    ----------
    file_name : str or pathlib.Path
        HEALPix gravitational-wave probability map, e.g. a BAYESTAR or
        LALInference FITS file with a ``PROB`` column.
    levels : iterable of float
        Credible levels, in percent, to draw. Values such as ``(5, 25, 50)``
        outline the smallest sky regions containing those probabilities.
    mw_image : str or pathlib.Path, optional
        Background image. Defaults to ``data/MW_edgeon_edr3_unannotate.jpg``.
        If the image is missing, contours are drawn on a white background.
    colors : sequence, optional
        One color per level. If omitted, distinct colors are selected from
        matplotlib's ``plasma`` colormap.
    fill_alpha : float
        Alpha for the filled credible-level regions.
    line_alpha : float
        Alpha for the contour lines.
    linewidth : float
        Width of the contour lines.
    grid_shape : tuple of int
        Latitude and longitude sample counts used to project the HEALPix map.
    figsize : tuple of float
        Figure size passed to matplotlib.
    save_figure : str or pathlib.Path, optional
        If given, save the figure to this path.
    return_fig : bool
        If True, return the matplotlib figure.
    """
    levels = _normalise_levels(levels)
    mw_image = Path(mw_image) if mw_image is not None else _default_mw_image_path()
    has_mw_image = mw_image.exists()
    if not has_mw_image:
        print(
            f"Milky Way background image not found: {mw_image}. "
            "Plotting contours on a white background."
        )

    x_galactic, y_galactic, confidence_grid, map_header = _gw_confidence_grid(
        file_name, grid_shape=grid_shape
    )

    if colors is None:
        cmap = plt.get_cmap("plasma")
        colors = [cmap(value) for value in np.linspace(0.15, 0.85, len(levels))]
    elif len(colors) != len(levels):
        raise ValueError("colors must contain one color per credible level.")

    fig, ax = plt.subplots(figsize=figsize)
    ax.set_facecolor("white")
    if has_mw_image:
        ax.imshow(
            plt.imread(mw_image),
            extent=[-180.0, 180.0, -90.0, 90.0],
            origin="upper",
            aspect="auto",
            zorder=0,
        )

    filled_levels = [0.0, *levels]
    ax.contourf(
        x_galactic,
        y_galactic,
        confidence_grid,
        levels=filled_levels,
        colors=colors,
        alpha=fill_alpha,
        antialiased=True,
        zorder=2,
    )

    line_contours = ax.contour(
        x_galactic,
        y_galactic,
        confidence_grid,
        levels=levels,
        colors=colors,
        linewidths=linewidth,
        alpha=line_alpha,
        zorder=3,
    )
    ax.clabel(line_contours, fmt=lambda level: f"{level:g}%", fontsize=8)

    object_name = map_header.get("OBJECT", "GW event")
    date_obs = map_header.get("DATE", "")
    title = f"{object_name} GW credible regions"
    if date_obs:
        title = f"{title} ({date_obs})"
    ax.set_title(title)
    ax.set_xlabel("Galactic longitude, -l (deg)")
    ax.set_ylabel("Galactic latitude (deg)")
    ax.set_xlim(-180.0, 180.0)
    ax.set_ylim(-90.0, 90.0)
    grid_color = "white" if has_mw_image else "0.65"
    ax.grid(True, ls=":", alpha=0.25, color=grid_color, zorder=1)

    if save_figure is not None:
        fig.savefig(save_figure, bbox_inches="tight", dpi=200)

    if return_fig:
        return fig
    return None


def _mjd_from_headers(*headers) -> float | None:
    for header in headers:
        if header is None:
            continue
        if "MJD-OBS" in header:
            return float(header["MJD-OBS"])
        if "DATE-OBS" in header:
            return float(Time(header["DATE-OBS"], format="isot").mjd)
    return None


def event_mjd_from_gw(file_name: str | Path) -> float:
    """Return the GW trigger time as MJD from a skymap FITS header."""
    with fits.open(file_name, memmap=False) as hdul:
        for hdu in hdul:
            mjd = _mjd_from_headers(hdu.header)
            if mjd is not None:
                return mjd
    raise ValueError(f"Could not find MJD-OBS or DATE-OBS in {file_name}.")


def _as_1d_spectrum_array(values) -> np.ndarray:
    values = np.asarray(values)
    if values.ndim == 0:
        return values.reshape(1)
    return np.ravel(values[0] if values.ndim > 1 else values)


def _read_1d_spectrum(data_file: str | Path, *, flux_column: str = "FLUX",
                      use_mid_exposure: bool = True) -> dict:
    data_file = Path(data_file)
    with fits.open(data_file, memmap=False) as hdul:
        primary_header = hdul[0].header
        for hdu in hdul[1:]:
            data = hdu.data
            column_names = set(getattr(data, "names", None) or [])
            if "WAVE" not in column_names or flux_column not in column_names:
                continue

            wave = _as_1d_spectrum_array(data["WAVE"]).astype(float)
            flux = _as_1d_spectrum_array(data[flux_column]).astype(float)
            quality = (
                _as_1d_spectrum_array(data["QUAL"]).astype(int)
                if "QUAL" in column_names
                else np.zeros_like(wave, dtype=int)
            )

            valid = np.isfinite(wave) & np.isfinite(flux) & (quality == 0)
            valid &= flux != 0.0
            wave = wave[valid]
            flux = flux[valid]

            if wave.size == 0:
                raise ValueError(f"No valid spectrum samples found in {data_file}.")

            wave_unit = hdu.header.get("TUNIT1", "")
            if wave_unit.lower() in {"nm", "nanometer", "nanometers"}:
                wave = wave / 1000.0
            elif wave_unit.lower() in {"angstrom", "angstroms", "aa"}:
                wave = wave / 10000.0
            elif np.nanmedian(wave) > 50.0:
                wave = wave / 1000.0

            mjd = _mjd_from_headers(primary_header, hdu.header)
            if mjd is None:
                raise ValueError(f"Could not find MJD-OBS or DATE-OBS in {data_file}.")

            exptime = float(primary_header.get("EXPTIME", hdu.header.get("EXPTIME", 0.0)))
            if use_mid_exposure:
                mjd += 0.5 * exptime / 86400.0

            return {
                "file": data_file,
                "wave": wave,
                "flux": flux,
                "mjd": mjd,
                "instrument": primary_header.get("INSTRUME", ""),
                "category": primary_header.get("HIERARCH ESO PRO CATG", ""),
            }

    raise ValueError(f"Could not find WAVE and {flux_column} columns in {data_file}.")


def _group_spectra_by_epoch(spectra: list[dict], *, tolerance_days: float = 0.2) -> list[list[dict]]:
    spectra = sorted(spectra, key=lambda spectrum: spectrum["mjd"])
    groups: list[list[dict]] = []
    for spectrum in spectra:
        if (
            not groups
            or abs(spectrum["mjd"] - np.mean([item["mjd"] for item in groups[-1]]))
            > tolerance_days
        ):
            groups.append([spectrum])
        else:
            groups[-1].append(spectrum)
    return groups


def _smooth_nan_array(values: np.ndarray, window: int) -> np.ndarray:
    if window <= 1:
        return values

    kernel = np.ones(int(window), dtype=float)
    valid = np.isfinite(values)
    numerator = np.convolve(np.where(valid, values, 0.0), kernel, mode="same")
    denominator = np.convolve(valid.astype(float), kernel, mode="same")

    smoothed = np.full_like(values, np.nan, dtype=float)
    np.divide(numerator, denominator, out=smoothed, where=denominator > 0)
    return smoothed


def show_xshooter_spectra_from_gw(data_files, *, event_file: str | Path | None = None,
                         event_mjd: float | None = None, flux_column: str = "FLUX",
                         epoch_tolerance_days: float = 0.2,
                         clip_percentiles: tuple[float, float] = (2.0, 98.0),
                         smooth_samples: int = 101,
                         use_mid_exposure: bool = True,
                         normalize: bool = True,
                         normalise: bool | None = None,
                         offset: float = 0.4, label_phase_decimals: int = 1,
                         colors=None, figsize: tuple[float, float] = (5.0, 11.0),
                         save_figure: str | Path | None = None,
                         return_fig: bool = False):
    """
    Plot an offset montage of X-shooter spectra by phase after a GW trigger.

    Parameters
    ----------
    data_files : iterable of str or pathlib.Path
        One-dimensional spectrum FITS files with ``WAVE`` and ``FLUX`` columns.
        Multiple X-shooter arms from the same epoch are grouped together.
    event_file : str or pathlib.Path, optional
        GW skymap FITS file used to read the trigger ``MJD-OBS``.
    event_mjd : float, optional
        Trigger time in MJD. Overrides ``event_file`` when supplied.
    flux_column : str
        Spectrum table column to plot, usually ``FLUX`` or ``FLUX_REDUCED``.
    epoch_tolerance_days : float
        Maximum MJD separation for grouping files into one epoch.
    clip_percentiles : tuple of float
        Display clipping percentiles used before normalizing each epoch. This
        suppresses strong edge artifacts without changing the input data.
    smooth_samples : int
        Width, in native spectral samples, of the display smoothing window. Use
        1 to plot unsmoothed spectra.
    use_mid_exposure : bool
        If True, label phases using ``MJD-OBS + EXPTIME / 2``.
    normalize : bool
        If True, subtract a robust baseline and divide by a robust flux scale
        before applying the vertical offset. If False, plot the raw flux values
        and add the offset directly in the same flux units.
    normalise : bool, optional
        British spelling alias for ``normalize``. If supplied, this overrides
        ``normalize``.
    offset : float
        Vertical spacing between spectra. In normalized mode this is in
        normalized brightness units; otherwise it is in the same units as
        ``flux_column``.
    label_phase_decimals : int
        Number of decimals shown in the phase labels.
    colors : sequence, optional
        One color per epoch. If omitted, colors run from blue to orange.
    figsize : tuple of float
        Figure size passed to matplotlib.
    save_figure : str or pathlib.Path, optional
        If given, save the figure to this path.
    return_fig : bool
        If True, return the matplotlib figure.
    """
    data_files = [Path(data_file) for data_file in data_files]
    if not data_files:
        raise ValueError("At least one spectrum file is required.")

    if event_mjd is None:
        if event_file is None:
            raise ValueError("Provide either event_mjd or event_file.")
        event_mjd = event_mjd_from_gw(event_file)
    if normalise is not None:
        normalize = normalise

    spectra = [
        _read_1d_spectrum(
            data_file,
            flux_column=flux_column,
            use_mid_exposure=use_mid_exposure,
        )
        for data_file in data_files
    ]
    epoch_groups = _group_spectra_by_epoch(spectra, tolerance_days=epoch_tolerance_days)
    epoch_groups = sorted(epoch_groups, key=lambda group: np.mean([item["mjd"] for item in group]))

    if colors is None:
        cmap = plt.get_cmap("turbo")
        colors = [cmap(value) for value in np.linspace(0.05, 0.8, len(epoch_groups))]
    elif len(colors) != len(epoch_groups):
        raise ValueError("colors must contain one color per epoch.")

    fig, ax = plt.subplots(figsize=figsize)
    label_x = 0.02
    max_offset = offset * (len(epoch_groups) - 1)
    y_min = np.inf
    y_max = -np.inf

    for epoch_index, group in enumerate(epoch_groups):
        phase = np.mean([spectrum["mjd"] for spectrum in group]) - event_mjd
        y_offset = max_offset - epoch_index * offset
        color = colors[epoch_index]

        if normalize:
            all_flux = np.concatenate([spectrum["flux"] for spectrum in group])
            low_clip, high_clip = np.nanpercentile(all_flux, clip_percentiles)
            scale = high_clip - low_clip
            if not np.isfinite(scale) or scale <= 0:
                low_clip = np.nanpercentile(all_flux, 5.0)
                high_clip = np.nanpercentile(all_flux, 95.0)
                scale = high_clip - low_clip
            if not np.isfinite(scale) or scale <= 0:
                low_clip = 0.0
                scale = 1.0

        for spectrum in sorted(group, key=lambda item: np.nanmedian(item["wave"])):
            flux = spectrum["flux"].copy()
            if normalize:
                flux[(flux < low_clip) | (flux > high_clip)] = np.nan
                y = (flux - low_clip) / scale
            else:
                y = flux
            y = _smooth_nan_array(y, smooth_samples)
            y_plot = y + y_offset
            finite_y = y_plot[np.isfinite(y_plot)]
            if finite_y.size:
                y_min = min(y_min, float(np.nanmin(finite_y)))
                y_max = max(y_max, float(np.nanmax(finite_y)))
            ax.plot(spectrum["wave"], y_plot, color=color, lw=0.7)

        phase_label = f"{phase:.{label_phase_decimals}f}"
        ax.text(
            label_x - 0.075,
            y_offset + (0.5 if normalize else 0.0),
            phase_label,
            color="white",
            fontsize=14,
            ha="left",
            va="center",
            bbox={"boxstyle": "square,pad=0.18", "facecolor": color, "edgecolor": color},
        )

    ax.set_xlabel(r"Wavelength ($\mu$m)")
    ax.set_ylabel("Brightness")
    ax.set_xlim(-0.1, 2.5)
    if normalize:
        ax.set_ylim(0.3, max_offset + 1)
    elif np.isfinite(y_min) and np.isfinite(y_max):
        y_margin = 0.05 * (y_max - y_min) if y_max > y_min else 1.0
        ax.set_ylim(y_min - y_margin, y_max + y_margin)
    ax.set_yticks([])
    ax.tick_params(which="both", direction="in", top=True, right=True)
    ax.minorticks_on()

    ax.set_title("X-shooter spectra after GW trigger", fontsize=15, fontweight="bold")

    if save_figure is not None:
        fig.savefig(save_figure, bbox_inches="tight", dpi=200)

    if return_fig:
        return fig
    return None


def _array_split(array_in: np.ndarray, threshold: float):
    xx_in, yy_in = array_in[:, 0], array_in[:, 1]
    ii = np.argmax(xx_in)
    xx_in = np.append(xx_in[ii:], xx_in[0:ii])
    yy_in = np.append(yy_in[ii:], yy_in[0:ii])

    dxx = np.diff(xx_in)
    split_indices = np.where(np.abs(dxx) > threshold)
    return np.split(xx_in, split_indices[0] + 1), np.split(yy_in, split_indices[0] + 1)


def contour_to_polygon(contour: list[list[float]], max_vertices: int = 30) -> str:
    """
    Convert one contour to a polygon vertex string accepted by ASP/TAP queries.

    The serialized polygon is intentionally left open, matching the Science
    Portal `poly=` format, i.e. we do not repeat the first vertex at the end.
    """
    contour_array = _continuous_contour_vertices(_ensure_counterclockwise(contour))
    if len(contour_array) > max_vertices:
        step = int(len(contour_array) / max_vertices + 1)
        contour_array = contour_array[::step]

    if len(contour_array) == 0:
        return ""

    return ",".join(f"{ra:.5f},{dec:.5f}" for ra, dec in contour_array)


def contours_to_polygons(contours, max_vertices: int = 30) -> list[str]:
    """Convert all contours into polygon strings."""
    if not contours:
        return []
    return [contour_to_polygon(contour, max_vertices=max_vertices) for contour in contours]


def build_science_portal_urls_from_polygons(polygons, *, instruments=None, data_types=None,
                                            sort: str = "-obs_date") -> list[str]:
    """Build Science Portal URLs for one or more polygons."""
    if isinstance(polygons, str):
        polygons = [polygons]

    def _join(values):
        if values is None:
            return None
        if isinstance(values, str):
            values = [values]
        return ",".join(str(v).upper() for v in values)

    urls = []
    for polygon in polygons:
        query_parts = [f"poly={polygon}", f"sort={sort}"]
        if instruments:
            query_parts.append(f"ins_id={_join(instruments)}")
        if data_types:
            query_parts.append(f"dp_type={_join(data_types)}")
        urls.append("https://archive.eso.org/scienceportal/home?" + "&".join(query_parts))
    return urls
