from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import numpy as np
import requests
from astropy.utils.data import download_file

try:
    from tqdm import tqdm

    _HAS_TQDM = True
except Exception:
    _HAS_TQDM = False


def _sanitize_filename(name: str) -> str:
    """Make a safe filename across platforms."""
    bad = r'\/:*?"<>|'
    return "".join("_" if c in bad else c for c in name)


def _build_soda_url(dp_id, ra, dec, radius, wave_min=None, wave_max=None, prefix=None) -> str:
    """
    Build the SODA sync URL for the ESO Data Portal.

    CIRCLE is written as RA DEC RADIUS in degrees. BAND is written with lower
    and upper wavelength bounds, typically in meters for these MUSE cutouts.
    """
    base = "https://dataportal.eso.org/dataPortal/soda/sync"
    parts = [f"ID={dp_id}", f"CIRCLE={ra}+{dec}+{radius}"]
    if wave_min is not None and wave_max is not None:
        parts.append(f"BAND={wave_min}+{wave_max}")
    if prefix:
        parts.append(f"PREFIX={prefix}")
    return f"{base}?{'&'.join(parts)}"


def _human_size(nbytes: int | None) -> str:
    if nbytes is None:
        return "unknown"

    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(nbytes)
    for unit in units:
        if size < 1000 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1000.0
    return f"{nbytes} B"


def _content_length(url: str, timeout: int = 600) -> int | None:
    """
    Try to get the size in bytes from server headers.

    Some servers reject HEAD requests, so this falls back to a streamed GET that
    reads only the response headers.
    """
    try:
        response = requests.head(url, timeout=timeout, allow_redirects=True)
        content_length = response.headers.get("Content-Length")
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
    ra,
    dec,
    radius,
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
    """
    Request a cutout from the ESO Data Portal SODA service.

    Parameters
    ----------
    dp_id : str
        ESO data product identifier.
    ra, dec : float
        Cutout centre in decimal degrees.
    radius : float
        Circular cutout radius in degrees.
    wave_min, wave_max : float, optional
        Lower and upper wavelength bounds. For these MUSE products the values
        are supplied in meters.
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
        Local filepath when ``download=True``; otherwise the constructed SODA URL.
    """
    radius = float(np.round(radius, 6))
    url = _build_soda_url(dp_id, ra, dec, radius, wave_min, wave_max, prefix)

    if verbose:
        print(f"Requesting cutout from URL: {url}")

    if not download:
        if print_size:
            size = _content_length(url, timeout=timeout)
            if size is not None:
                print(f"Server reports size: {_human_size(size)}")
            else:
                print("Server did not report a size.")
        return url

    outdir = Path(outdir) if outdir is not None else Path.cwd()
    outdir.mkdir(parents=True, exist_ok=True)
    if outfile is not None:
        out_path = outdir / _sanitize_filename(str(outfile))
    else:
        out_path = outdir / _sanitize_filename(f"{dp_id}.fits")

    if out_path.exists() and not overwrite:
        raise FileExistsError(f"{out_path} exists (set overwrite=True to replace).")

    if progress_backend == "tqdm" and _HAS_TQDM:
        size = _content_length(url, timeout=timeout)
        if print_size:
            print(f"Estimated download size: {_human_size(size)}")

        with requests.get(url, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length", 0)) or None
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp_name = tmp.name
            try:
                chunk = 1000 * 1000
                pbar = None
                if show_progress:
                    pbar = tqdm(
                        total=total,
                        unit="B",
                        unit_scale=True,
                        unit_divisor=1000,
                        desc="Downloading",
                        leave=True,
                    )
                with open(tmp_name, "wb") as handle:
                    for part in response.iter_content(chunk_size=chunk):
                        if not part:
                            continue
                        handle.write(part)
                        if pbar is not None:
                            pbar.update(len(part))
                if pbar is not None:
                    pbar.close()
                if out_path.exists() and overwrite:
                    out_path.unlink()
                shutil.move(tmp_name, out_path)
            except Exception:
                try:
                    os.remove(tmp_name)
                except Exception:
                    pass
                raise

    elif progress_backend == "astropy":
        if print_size:
            size = _content_length(url, timeout=timeout)
            if size is not None:
                print(f"Estimated download size: {_human_size(size)}")
            else:
                print("Server did not report a size.")
        tmp_path = Path(
            download_file(url, cache=False, show_progress=show_progress, timeout=timeout)
        )
        if out_path.exists() and overwrite:
            out_path.unlink()
        shutil.move(str(tmp_path), str(out_path))

    else:
        if print_size:
            size = _content_length(url, timeout=timeout)
            if size is not None:
                print(f"Estimated download size: {_human_size(size)}")
        with requests.get(url, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp_name = tmp.name
            try:
                with open(tmp_name, "wb") as handle:
                    for part in response.iter_content(chunk_size=1024 * 1024):
                        if part:
                            handle.write(part)
                if out_path.exists() and overwrite:
                    out_path.unlink()
                shutil.move(tmp_name, out_path)
            except Exception:
                try:
                    os.remove(tmp_name)
                except Exception:
                    pass
                raise

    if verbose:
        print(f"Wrote: {out_path}")
    return str(out_path)


def get_wavelengthaxis(hdul, index=1):
    """
    Compute the spectral wavelength axis from a FITS HDUList.

    The function reads the header of extension ``index`` and assumes the third
    axis is spectral and linear. The returned values have the units implied by
    the header, typically Angstrom for these MUSE cutouts.
    """
    hdr = hdul[index].header
    crval = hdr["CRVAL3"]
    cdelt = hdr["CD3_3"]
    crpix = hdr["CRPIX3"]
    naxis = hdr["NAXIS3"]
    return crval + (np.arange(naxis) + 1 - crpix) * cdelt
