# Repository Instructions

This repository contains Jupyter notebooks that teach users how to work with the
ESO Science Archive through `astroquery.eso`. Treat notebooks as final user-facing
examples, not scratch material.

## Notebook Style

When creating or editing notebooks, match the structure and tone of the existing
examples, especially:

- `examples/advanced/09_compare_catalogs.ipynb`
- `examples/advanced/10_linked_catalog_lightcurves.ipynb`
- `examples/advanced/11_link_catalogs_and_observations.ipynb`

Use the current notebook style consistently:

- Start with `<hr style="border:2px solid #0281c9"> </hr>`.
- Use a bold title heading such as `# **Query Linked Catalogue Tables in the VVVX Survey**`.
- Include a setup section named `# **Importing and basic usage of astroquery.eso**`.
- Use bold markdown headings for major sections and subsections, for example
  `# **Discover the catalogue tables to compare**` or
  `## **Inspect one catalogue in log-scaled density**`.
- Add clear narrative markdown before major code cells. Explain what the next
  query, transformation, plot, or download is intended to demonstrate.
- Keep the tone practical and scientific: enough context for an archive user to
  understand the workflow, without referring to implementation history or drafts.
- Structure examples around a clear arc: scientific motivation, archive or
  catalogue discovery, schema inspection, query execution, result inspection,
  and optional plotting or download.

## `astroquery.eso` Usage

Prefer the public `astroquery.eso` interface used by the notebooks:

```python
import astroquery
print(f"astroquery version: {astroquery.__version__}")

from astroquery.eso import Eso
eso = Eso()
```

Use high-level helpers where they fit the example:

- `eso.query_surveys(...)` for reduced Phase 3 products.
- `eso.query_main(...)` for generic raw observation searches.
- `eso.query_instrument(...)` for instrument-specific raw searches.
- `eso.query_catalog(...)` for ESO catalogue table queries.
- `eso.query_tap(...)` for custom ADQL.
- `eso.retrieve_data(...)` for downloads.
- `eso.get_headers(...)` for FITS header retrieval.

For catalogue TAP examples, use the repository's current pattern:

```python
rows = eso.query_tap(query, tap_endpoint="tap_cat")
```

Before hard-coding table or column names, inspect schemas with TAP metadata,
`help=True`, or relevant discovery helpers. Use safe row limits for examples and
avoid uncontrolled full-table queries unless the query is tightly constrained and
the notebook explains why it is safe.

## Placement And Naming

Place new notebooks according to their purpose:

- `examples/simple/`: minimal, single-feature recipes.
- `examples/advanced/`: scenario-driven workflows that link multiple archive or
  catalogue capabilities.
- `examples/case_studies/`: curated, collection-specific or release-specific
  stories.

Use numbered, underscore-separated filenames, following the local sequence in the
target folder. When adding or renaming a notebook, update the corresponding
folder `README.md` so the index stays accurate.

## Translating Drafts Or External Material

External notebooks, attachments, or examples are source material only. The final
notebook must read as a standalone ESO Science Archive example:

- Do not refer to the original notebook, attachment, draft, or translation.
- Rewrite markdown, headings, and comments in this repository's style.
- Keep the information level aligned with nearby notebooks, especially the
  advanced catalogue examples listed above.
- Preserve the useful scientific workflow, but adapt it to the current
  `astroquery.eso` API and notebook conventions.

## Outputs And Data Hygiene

- Save generated figures under the relevant `figures/` directory.
- Save downloaded files under the relevant `data/` directory.
- Avoid committing large generated downloads, caches, temporary files, or
  `__pycache__` directories.
- Keep notebook outputs small and pedagogically useful. Clear heavy outputs
  before committing unless they are necessary for the example.
- Do not modify unrelated notebooks, generated data, or user work while making
  focused documentation or notebook changes.
