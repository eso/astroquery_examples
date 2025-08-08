<h1 style="text-align: center;">
  <img src="http://archive.eso.org/i/esologo.png" alt="ESO Logo" width="50" style="vertical-align: middle;">
  ESO Science Archive - Jupyter Notebooks
</h1>

# 📚 Examples

A guided tour of notebooks for working with the ESO Science Archive via `astroquery.eso`.

## What’s inside

* **[`simple/`](./simple/)** — 🌱 Minimal, single-feature recipes (copy/paste friendly; quick to run).
* **[`advanced/`](./advanced/)** — 🚀 Scenario-driven workflows that combine multiple functions.
* **[`highlights/`](./highlights/)** — 🌌 Curated, collection-specific case studies (often tied to new Phase 3 collections/releases).

## Start here

1. **[`simple/00_introduction.ipynb`](./simple/00_introduction.ipynb)** — repo overview, how to run, common imports.

## Conventions

* 🔢 Notebooks are **numbered** to suggest a reading order.
* 🧩 File names use **underscores**; directories use **short, lowercase names**.
* 📦 Data are **downloaded on demand**; the repo doesn’t ship large files.
* 🔐 Auth is required for some queries (but none included here) — see `simple/01_authentication.ipynb`.
* 🧹 To keep diffs small, clear heavy outputs before committing you own notebooks!

## Tips

* If a cell hangs on download, check network/VPN and rerun the cell.
* For TAP/ADQL quirks, start with `simple/06_query_tap.ipynb`, then see `advanced/` for more real-world examples.
* Opening issues/PRs with additional notebooks is 💯 welcome!!