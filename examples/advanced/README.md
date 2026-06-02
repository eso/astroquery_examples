<h1 style="text-align: center;">
  <img src="http://archive.eso.org/i/esologo.png" alt="ESO Logo" width="50" style="vertical-align: middle;">
  ESO Science Archive - Jupyter Notebooks
</h1>

# 🚀 Advanced examples

Use-case notebooks that combine multiple `astroquery.eso` functions into end-to-end workflows.
Expect more moving parts, larger queries, and longer runtimes.

## What you’ll practice
- 🔗 Mixing raw/reduced queries and following associations
- 🧭 Cross-instrument searches and overlap logic
- 🔭 Spectral extraction and simple QA
- 🧵 TAP/SSA usage in realistic pipelines
- 📈 Generating figures/animations for quick-look checks

## Notebooks
- **01_aladin_workflow.ipynb** — Side-by-side sky views with `ipyaladin`; surveys, overlays, exports.
- **02_raw_to_reduced.ipynb** — From raw observations to associated Phase 3 products (linking & filtering).
- **03_spectral_extraction.ipynb** — Extract and plot spectra from cubes or 1D spectral products.
- **04_time_series_spectra.ipynb** — Build and inspect time-resolved spectra (stacking, alignment, variability).
- **05a_alpaca_darksky_monitoring.ipynb** — Query ALPACA dark-sky monitoring products and inspect observing conditions.
- **05b_astronomical_dawn_analysis.ipynb** — Analyse astronomical dawn timing and atmospheric context.
- **06_ssa_query_and_download.ipynb** — Search and download 1D spectra via SSA; quick sanity checks.
- **07_multi_instrument_overlap_download.ipynb** — Find targets with multi-instrument coverage; batch downloads.
- **08_meteo_paranal_simple_query.ipynb** — Query Paranal meteorological telemetry and make a grouped weather quick-look plot.
- **09_compare_catalogs.ipynb** — Discover catalogue tables via `tap_cat`, retrieve matched physical parameters, and compare parameter-space coverage across collections.
- **10_linked_catalog_lightcurves.ipynb** — Use linked VVVX catalogue tables to move from source positions to time-series data and plot light curves.
- **11_link_catalogs_and_observations.ipynb** — Select sources from catalogue parameters, search public Phase 3 spectra at their positions, and inspect one matched product.
- **12_query_ancillary_files.ipynb** — Query Phase 3 science and ancillary file components via `phase3v2.product_files`.

## Folders
- 📁 **data/** — outputs written/read by notebooks.
- 🖼️ **figures/** — images/animations produced by the notebooks.
