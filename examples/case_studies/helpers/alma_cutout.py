from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlencode

import requests
from astropy.utils.data import download_file

try:
    from tqdm import tqdm

    _HAS_TQDM = True
except Exception:
    _HAS_TQDM = False


SODA_URL = "https://almascience.eso.org/soda/sync"


def _sanitize_filename(name: str) -> str:
    """Make a safe filename across platforms."""
    bad = r'\/:*?"<>|'
    return "".join("_" if character in bad else character for character in name)


def _build_soda_url(
    dp_id, ra, dec, radius, wave_min=None, wave_max=None, prefix=None
) -> str:
    """Build an ALMA SODA sync URL."""
    params = [("REQUEST", "queryData"), ("ID", str(dp_id))]
    if ra is not None and dec is not None and radius is not None:
        params.append(("POS", f"CIRCLE {ra} {dec} {radius}"))
    if wave_min is not None and wave_max is not None:
        params.append(("BAND", f"{wave_min} {wave_max}"))
    if prefix:
        params.append(("PREFIX", str(prefix)))
    return f"{SODA_URL}?{urlencode(params)}"


def _human_size(nbytes: int | None) -> str:
    if nbytes is None:
        return "unknown"

    size = float(nbytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1000 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1000.0
    return f"{nbytes} B"


def _content_length(url: str, timeout: int = 600) -> int | None:
    """Return the server-reported response size, when available."""
    try:
        response = requests.head(url, timeout=timeout, allow_redirects=True)
        content_length = response.headers.get("Content-Length")
        response.close()
        if content_length is not None:
            return int(content_length)

        response = requests.get(url, timeout=timeout, stream=True)
        content_length = response.headers.get("Content-Length")
        response.close()
        return int(content_length) if content_length is not None else None
    except Exception:
        return None


def get_cutout(
    dp_id,
    ra=None,
    dec=None,
    radius=None,
    wave_min=None,
    wave_max=None,
    prefix=None,
    *,
    outdir: str | Path | None = None,
    outfile: str | Path | None = None,
    verbose: bool = False,
    download: bool = True,
    show_progress: bool = True,
    timeout: int = 600,
    overwrite: bool = False,
    print_size: bool = True,
    progress_backend: str = "tqdm",
) -> str:
    """Request an ALMA product or cutout from the ALMA SODA service.

    Parameters
    ----------
    dp_id : str
        ALMA SODA dataset identifier or product filename.
    ra, dec : float, optional
        Cutout centre in ICRS decimal degrees. Omit together with ``radius``
        to request the full spatial extent of the product.
    radius : float, optional
        Circular cutout radius in degrees.
    wave_min, wave_max : float, optional
        Lower and upper wavelength bounds in metres.
    prefix : str, optional
        Optional SODA prefix parameter.
    outdir : str or pathlib.Path, optional
        Output directory used when ``download=True``.
    outfile : str or pathlib.Path, optional
        Output filename. Defaults to ``<dp_id>.fits``.
    verbose : bool
        If True, print the request URL and final output path.
    download : bool
        If False, return the constructed SODA URL without downloading.
    show_progress : bool
        If True, display download progress where supported.
    timeout : int
        Request timeout in seconds.
    overwrite : bool
        If True, replace an existing output file.
    print_size : bool
        If True, print the server-reported size when available.
    progress_backend : {"tqdm", "astropy", "none"}
        Progress display for downloads.

    Returns
    -------
    str
        Local filepath when ``download=True``; otherwise the SODA URL.
    """
    spatial_values = (ra, dec, radius)
    if any(value is None for value in spatial_values) and not all(
        value is None for value in spatial_values
    ):
        raise ValueError("ra, dec, and radius must either all be supplied or all be None.")
    if (wave_min is None) != (wave_max is None):
        raise ValueError("wave_min and wave_max must either both be supplied or both be None.")
    if radius is not None:
        radius = round(float(radius), 6)

    url = _build_soda_url(dp_id, ra, dec, radius, wave_min, wave_max, prefix)
    if verbose:
        print(f"Requesting cutout from URL: {url}")

    if not download:
        if print_size:
            size = _content_length(url, timeout=timeout)
            print(
                f"Server reports size: {_human_size(size)}"
                if size is not None
                else "Server did not report a size."
            )
        return url

    outdir = Path(outdir) if outdir is not None else Path.cwd()
    outdir.mkdir(parents=True, exist_ok=True)
    output_name = str(outfile) if outfile is not None else f"{dp_id}.fits"
    out_path = outdir / _sanitize_filename(output_name)

    if out_path.exists() and not overwrite:
        print(f"{out_path} exists (set overwrite=True to replace). Skipping download.")
        return str(out_path)

    if print_size:
        size = _content_length(url, timeout=timeout)
        if size is not None:
            print(f"Estimated download size: {_human_size(size)}")
        else:
            print("Server did not report a size.")

    if progress_backend == "astropy":
        tmp_path = Path(
            download_file(url, cache=False, show_progress=show_progress, timeout=timeout)
        )
        if out_path.exists():
            out_path.unlink()
        shutil.move(str(tmp_path), str(out_path))
    else:
        with requests.get(url, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length", 0)) or None
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp_name = tmp.name

            progress = None
            try:
                if progress_backend == "tqdm" and _HAS_TQDM and show_progress:
                    progress = tqdm(
                        total=total,
                        unit="B",
                        unit_scale=True,
                        unit_divisor=1000,
                        desc="Downloading",
                        leave=True,
                    )
                with open(tmp_name, "wb") as handle:
                    for part in response.iter_content(chunk_size=1024 * 1024):
                        if not part:
                            continue
                        handle.write(part)
                        if progress is not None:
                            progress.update(len(part))
                if out_path.exists():
                    out_path.unlink()
                shutil.move(tmp_name, out_path)
            except Exception:
                try:
                    os.remove(tmp_name)
                except OSError:
                    pass
                raise
            finally:
                if progress is not None:
                    progress.close()

    if verbose:
        print(f"Wrote: {out_path}")
    return str(out_path)
