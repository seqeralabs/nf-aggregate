# extract_tarball

Purpose
- Extract external run-data tarballs into directories of JSON artifacts.

Owns
- `EXTRACT_TARBALL` in `main.nf`

Inputs
- external tarball paths from the workflow routing layer

Outputs
- extracted directory per tarball
- `versions.yml`

Invariants
- Extraction only. Do not mix benchmark parsing or aggregation into this module.
- Downstream workflow code is responsible for collecting JSON files from extracted directories.

Edit guidance
- If tarball layout assumptions change, update the pipeline tarball scenario tests.
