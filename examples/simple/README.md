<h1 style="text-align: center;">
  <img src="http://archive.eso.org/i/esologo.png" alt="ESO Logo" width="50" style="vertical-align: middle;">
  ESO Science Archive - Jupyter Notebooks
</h1>

# 🌱 Simple examples

Small, self-contained notebooks that illustrate one `astroquery.eso` capability at a time.
Designed for quick copy/paste and minimal setup.

## Notebooks (suggested order)
1. **00_quickstart.ipynb** — Start with basic imports, raw and reduced observation searches, optional downloads, and a small catalogue query. 
2. **01_authentication.ipynb** — Log in, store credentials securely, and test an authenticated query. 
3. **02_query_observation_reduced_by_position.ipynb** — Find Phase 3 (reduced) data near a sky position.
4. **03_query_observation_raw_by_position.ipynb** — Find raw data near a sky position; compare to reduced searches.
5. **04_query_observation_by_program_id.ipynb** — Search by ESO Program ID and filter results.
6. **05_query_observation_apex.ipynb** — APEX-specific query patterns and common filters.
7. **06_query_observation_tap.ipynb** — Use TAP/ADQL for flexible archive queries (columns, constraints, joins).
8. **07_download_observation_data.ipynb** — Robust download patterns (credentials, retries, output layout).
9. **08_query_catalogue_with_constraints.ipynb** — Query catalogue tables with selected columns, simple ADQL-style filters, and a lightweight VIKING exploration example.
10. **09_query_catalogue_by_position.ipynb** — Query catalogue tables around a target position using an ADQL cone-search filter.
11. **10_query_catalogue_tap.ipynb** — Query catalogue metadata and content directly with ADQL through the catalogue TAP service.
