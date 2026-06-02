# Notebook Runner

Use `run_notebooks.py` to execute notebooks and get a pass/fail report without
stopping at the first failure.

Run this from the same conda or Python environment normally used for the
notebooks. For example:

```bash
conda activate astroquery_eso
python .tools/run_notebooks.py
```

The script prints the active Python executable, Python version, and detected
conda environment at startup so it is clear which environment is being used. It
also checks that `nbconvert` is available before it starts running notebooks.

If you see an error such as `Jupyter command jupyter-nbconvert not found`, the
active environment is missing `nbconvert`. Install it in the notebook
environment, then rerun the script:

```bash
conda install nbconvert
# or
python -m pip install nbconvert
```

## Common Commands

Run every notebook in the repository:

```bash
python .tools/run_notebooks.py
```

Run one notebook:

```bash
python .tools/run_notebooks.py --root examples/simple/00_introduction.ipynb
```

Run one folder:

```bash
python .tools/run_notebooks.py --root examples/simple
```

Set a per-notebook timeout:

```bash
python .tools/run_notebooks.py --timeout 300
```

View the latest log:

```bash
less .tools/notebook_run_report.log
```

## Where Outputs Go

Each notebook is executed with its own notebook directory as the working
directory. That means notebook-created downloads, `data/`, and `figures/` outputs
stay in the same places they normally would when running the notebook by hand.

Executed notebook copies are written to a temporary directory outside the repo
and are cleaned up automatically. Use `--keep-executed` only when you need those
copies for debugging.

Run `python .tools/run_notebooks.py --help` for all options.
