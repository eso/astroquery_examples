<h1 style="text-align: center;">
  <img src="http://archive.eso.org/i/esologo.png" alt="ESO Logo" width="50" style="vertical-align: middle;">
  ESO Science Archive - Jupyter Notebooks
</h1>

# 🌌 Case Studies (curated case studies or examples)

Collection, dataset, or release specific, end-to-end examples that showcase particular Phase 3 products.
Curated to highlight newly ingested datasets and how to work with them in practice
(some may also connect to [ESO press releases](https://www.eso.org/public/news/)).

## Notebooks
- **muse_ngc253_download_cutout_quicklook.ipynb**
  - **MUSE NGC 253 large mosaic:** This notebook demonstrates how to programmatically access and explore **The MUSE View of the Sculptor** data release. Instead of downloading the full **364 GB** mosaic cube, you’ll learn how to request smaller **cutouts** — spatially and/or spectrally cropped subsets — via ESO’s Science Archive Facility. These examples provide a quick way to explore the galaxy’s ionised gas, stars, and dust at high resolution.  
    - 📦 [ADP.2025-07-06T07:52:11.871](https://archive.eso.org/dataset/ADP.2025-07-06T07:52:11.871): full-resolution MUSE mosaic data cube preview
    - 📊 [Ancillary DAP maps (~10 GB)](https://dataportal.eso.org/dataPortal/file/ADP.2025-07-06T07:52:11.876): emission-line fluxes (e.g. Hα, [N II], [S II]), stellar and gas kinematics, moment maps  
    - 📝 [Official data release description](https://www.eso.org/rm/api/v1/public/releaseDescriptions/236): documentation for the Phase 3 collection
    - 📰 [ESO press release (eso2510)](https://www.eso.org/public/news/eso2510/): media highlights from eso  
- **gravitationalwave_event_search.ipynb**
  - **Gravitational-wave localization archive search:** This case study demonstrates how to find science-ready ESO observations inside gravitational-wave probability contours. It downloads or reuses skymaps from GraceDB and the LIGO Document Control Center, extracts credible-level contours, converts them into Science Portal and TAP polygon queries, searches `ivoa.ObsCore`, and optionally downloads matching products. The worked follow-up example focuses on **GW170817**, including reduced X-shooter spectra from the VLT and a reconstructed spectral-evolution montage of the kilonova in NGC 4993.
    - 📰 [ESO press release (eso1733)](https://www.eso.org/public/news/eso1733/): ESO observations of the first gravitational-wave source with an identified optical counterpart
    - 🌌 [GW170817 LIGO DCC event page](https://dcc.ligo.org/LIGO-G1701985/public): public event materials and localization products
    - 🔎 [GraceDB](https://gracedb.ligo.org/): gravitational-wave candidate event database used for BAYESTAR skymaps
- **More coming soon....**

## Folders
- 📁 **data/** — outputs written/read by notebooks.
- 🖼️ **figures/** — images/animations produced by the notebooks.
