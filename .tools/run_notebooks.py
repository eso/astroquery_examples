#!/usr/bin/env python3
"""Run repository notebooks and report pass/fail status.

Run this from the same conda or Python environment normally used for these
notebooks, for example:

    conda activate astroquery_eso
    python .tools/run_notebooks.py

Notebook-created files are written relative to each notebook's own directory.
Executed notebook copies are written to a temporary directory and cleaned up
unless --keep-executed is used.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import time
from datetime import datetime


EXCLUDED_DIRS = {".git", ".ipynb_checkpoints", ".pytest_cache", ".tools"}
DEFAULT_TIMEOUT_SECONDS = 1800
TAIL_LINES = 30


class Colors:
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def colorize(text: str, color: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"{color}{text}{Colors.RESET}"


def parse_args(repo_root: Path) -> argparse.Namespace:
    examples = f"""
examples:
  python {Path('.tools') / 'run_notebooks.py'}
  python {Path('.tools') / 'run_notebooks.py'} --root examples/simple/00_introduction.ipynb
  python {Path('.tools') / 'run_notebooks.py'} --root examples/simple
  python {Path('.tools') / 'run_notebooks.py'} --timeout 300
  python {Path('.tools') / 'run_notebooks.py'} --kernel python3 --no-color

notes:
  Run this from the same conda/Python environment normally used for the notebooks.
  The active environment must have nbconvert installed.
  Notebook downloads and outputs are written relative to each notebook's own folder.
  Executed notebook copies are temporary and cleaned unless --keep-executed is used.
"""
    parser = argparse.ArgumentParser(
        description="Execute notebooks and write a colorized pass/fail report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(examples),
    )
    parser.add_argument(
        "--root",
        default=str(repo_root),
        help="Repository root, subtree, or single notebook to run. Default: repo root.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Per-notebook timeout in seconds. Default: {DEFAULT_TIMEOUT_SECONDS}.",
    )
    parser.add_argument(
        "--kernel",
        help="Optional Jupyter kernel name to pass to nbconvert.",
    )
    parser.add_argument(
        "--log-file",
        default=str(repo_root / ".tools" / "notebook_run_report.log"),
        help="Path for the run log. Default: .tools/notebook_run_report.log.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colors in terminal output.",
    )
    parser.add_argument(
        "--keep-executed",
        action="store_true",
        help="Keep executed notebook copies for debugging instead of cleaning them.",
    )
    return parser.parse_args()


def resolve_path(path_text: str) -> Path:
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.parts)


def discover_notebooks(root: Path) -> list[Path]:
    if root.is_file():
        if root.suffix != ".ipynb":
            raise ValueError(f"--root points to a file that is not a notebook: {root}")
        if is_excluded(root):
            return []
        return [root]

    if not root.exists():
        raise FileNotFoundError(f"--root does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"--root is not a directory or notebook: {root}")

    notebooks = []
    for notebook in root.rglob("*.ipynb"):
        if not is_excluded(notebook):
            notebooks.append(notebook)
    return sorted(notebooks)


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(seconds, 60)
    return f"{int(minutes)}m {secs:.1f}s"


def tail(text: str, line_count: int = TAIL_LINES) -> str:
    lines = text.strip().splitlines()
    if not lines:
        return ""
    return "\n".join(lines[-line_count:])


def write_header(log_file: Path, args: argparse.Namespace, env_info: dict[str, str]) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("w", encoding="utf-8") as fh:
        fh.write("Notebook run report\n")
        fh.write("===================\n")
        fh.write(f"Started: {datetime.now().isoformat(timespec='seconds')}\n")
        fh.write(f"Command: {' '.join(sys.argv)}\n")
        fh.write(f"Selected root: {args.root}\n")
        fh.write(f"Timeout: {args.timeout}s\n")
        fh.write(f"Kernel: {args.kernel or '(default)'}\n")
        fh.write("\nEnvironment\n")
        fh.write("-----------\n")
        for key, value in env_info.items():
            fh.write(f"{key}: {value}\n")
        fh.write("\n")


def append_result(
    log_file: Path,
    notebook: Path,
    status: str,
    elapsed: float,
    returncode: int | str,
    stdout: str,
    stderr: str,
) -> None:
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write("\n")
        fh.write("-" * 80 + "\n")
        fh.write(f"Notebook: {notebook}\n")
        fh.write(f"Status: {status}\n")
        fh.write(f"Elapsed: {format_duration(elapsed)}\n")
        fh.write(f"Return code: {returncode}\n")
        if status != "PASS":
            fh.write("\nSTDOUT\n")
            fh.write("------\n")
            fh.write(stdout or "(empty)\n")
            if stdout and not stdout.endswith("\n"):
                fh.write("\n")
            fh.write("\nSTDERR\n")
            fh.write("------\n")
            fh.write(stderr or "(empty)\n")
            if stderr and not stderr.endswith("\n"):
                fh.write("\n")


def append_summary(log_file: Path, total: int, passed: int, failed: int, elapsed: float) -> None:
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write("\n")
        fh.write("=" * 80 + "\n")
        fh.write("Summary\n")
        fh.write("-------\n")
        fh.write(f"Total: {total}\n")
        fh.write(f"Passed: {passed}\n")
        fh.write(f"Failed: {failed}\n")
        fh.write(f"Elapsed: {format_duration(elapsed)}\n")
        fh.write(f"Finished: {datetime.now().isoformat(timespec='seconds')}\n")


def find_nbconvert() -> tuple[list[str] | None, str]:
    candidates = [
        ([sys.executable, "-m", "nbconvert"], f"{sys.executable} -m nbconvert"),
        (["jupyter", "nbconvert"], "jupyter nbconvert"),
        (["jupyter-nbconvert"], "jupyter-nbconvert"),
    ]
    errors = []
    for prefix, label in candidates:
        try:
            completed = subprocess.run(
                [*prefix, "--version"],
                text=True,
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"{label}: {exc}")
            continue
        if completed.returncode == 0:
            version = (completed.stdout or completed.stderr).strip() or "version unknown"
            return prefix, f"{label} ({version})"
        errors.append(f"{label}: {(completed.stderr or completed.stdout).strip()}")
    return None, "\n".join(errors)


def build_command(notebook: Path, output_dir: Path, args: argparse.Namespace) -> list[str]:
    command = [
        *args.nbconvert_command,
        "--to",
        "notebook",
        "--execute",
        notebook.name,
        "--output-dir",
        str(output_dir),
        "--output",
        notebook.name,
        f"--ExecutePreprocessor.timeout={args.timeout}",
    ]
    if args.kernel:
        command.append(f"--ExecutePreprocessor.kernel_name={args.kernel}")
    return command


def run_notebook(notebook: Path, repo_root: Path, temp_root: Path, args: argparse.Namespace):
    try:
        rel_parent = notebook.parent.relative_to(repo_root)
    except ValueError:
        rel_parent = Path("_outside_repo") / notebook.parent.name
    output_dir = temp_root / rel_parent
    output_dir.mkdir(parents=True, exist_ok=True)

    command = build_command(notebook, output_dir, args)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=notebook.parent,
            text=True,
            capture_output=True,
            timeout=args.timeout + 30,
        )
        elapsed = time.monotonic() - started
        return {
            "status": "PASS" if completed.returncode == 0 else "FAIL",
            "elapsed": elapsed,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - started
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        stderr = f"{stderr}\nNotebook timed out after {args.timeout}s.".strip()
        return {
            "status": "FAIL",
            "elapsed": elapsed,
            "returncode": "timeout",
            "stdout": stdout,
            "stderr": stderr,
        }


def print_environment(env_info: dict[str, str], selected_root: Path, color_enabled: bool) -> None:
    print(colorize("Environment reminder", Colors.BOLD, color_enabled))
    print("Run this from the same conda/Python environment normally used for these notebooks.")
    print(f"Python: {env_info['python']}")
    print(f"Python version: {env_info['python_version']}")
    print(f"Conda environment: {env_info['conda_environment']}")
    print(f"nbconvert: {env_info['nbconvert']}")
    print(f"Current working directory: {env_info['cwd']}")
    print(f"Selected notebook root: {selected_root}")
    print()


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    args = parse_args(repo_root)
    selected_root = resolve_path(args.root)
    log_file = resolve_path(args.log_file)
    color_enabled = not args.no_color

    env_info = {
        "python": sys.executable,
        "python_version": sys.version.replace("\n", " "),
        "conda_environment": os.environ.get("CONDA_DEFAULT_ENV", "not detected"),
        "cwd": str(Path.cwd()),
    }

    nbconvert_command, nbconvert_info = find_nbconvert()
    env_info["nbconvert"] = nbconvert_info

    print_environment(env_info, selected_root, color_enabled)
    write_header(log_file, args, env_info)

    if nbconvert_command is None:
        message = (
            "Could not find nbconvert in the active environment. Activate the notebook "
            "environment and install it with `conda install nbconvert` or "
            "`python -m pip install nbconvert`, then retry."
        )
        print(colorize(f"ERROR: {message}", Colors.RED, color_enabled))
        append_summary(log_file, total=0, passed=0, failed=1, elapsed=0.0)
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(f"\nERROR: {message}\n")
        return 2
    args.nbconvert_command = nbconvert_command

    try:
        notebooks = discover_notebooks(selected_root)
    except (FileNotFoundError, ValueError) as exc:
        print(colorize(f"ERROR: {exc}", Colors.RED, color_enabled))
        append_summary(log_file, total=0, passed=0, failed=1, elapsed=0.0)
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(f"\nERROR: {exc}\n")
        return 2

    if not notebooks:
        print(colorize("No notebooks found.", Colors.YELLOW, color_enabled))
        append_summary(log_file, total=0, passed=0, failed=0, elapsed=0.0)
        return 0

    print(f"Found {len(notebooks)} notebook(s).")
    print(f"Log file: {log_file}")
    print()

    temp_context = None
    if args.keep_executed:
        temp_root = Path(tempfile.mkdtemp(prefix="executed_notebooks_"))
        print(colorize(f"Keeping executed notebook copies in: {temp_root}", Colors.YELLOW, color_enabled))
    else:
        temp_context = tempfile.TemporaryDirectory(prefix="executed_notebooks_")
        temp_root = Path(temp_context.name)

    passed = 0
    failed = 0
    run_started = time.monotonic()

    try:
        for index, notebook in enumerate(notebooks, start=1):
            try:
                display_path = notebook.relative_to(repo_root)
            except ValueError:
                display_path = notebook

            print(f"[{index}/{len(notebooks)}] {display_path}")
            result = run_notebook(notebook, repo_root, temp_root, args)
            status = result["status"]
            elapsed = result["elapsed"]

            if status == "PASS":
                passed += 1
                label = colorize("PASS", Colors.GREEN, color_enabled)
                print(f"  {label} {format_duration(elapsed)}")
            else:
                failed += 1
                label = colorize("FAIL", Colors.RED, color_enabled)
                print(f"  {label} {format_duration(elapsed)}")
                detail = tail(result["stderr"] or result["stdout"])
                if detail:
                    print(colorize("  Failure detail:", Colors.RED, color_enabled))
                    print(textwrap.indent(detail, "    "))

            append_result(
                log_file=log_file,
                notebook=notebook,
                status=status,
                elapsed=elapsed,
                returncode=result["returncode"],
                stdout=result["stdout"],
                stderr=result["stderr"],
            )
            print()
    finally:
        if temp_context is not None:
            temp_context.cleanup()

    total_elapsed = time.monotonic() - run_started
    append_summary(log_file, total=len(notebooks), passed=passed, failed=failed, elapsed=total_elapsed)

    summary_color = Colors.GREEN if failed == 0 else Colors.RED
    print(colorize("Summary", Colors.BOLD, color_enabled))
    print(f"Total: {len(notebooks)}")
    print(colorize(f"Passed: {passed}", Colors.GREEN, color_enabled))
    print(colorize(f"Failed: {failed}", summary_color, color_enabled))
    print(f"Elapsed: {format_duration(total_elapsed)}")
    print(f"Log file: {log_file}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
