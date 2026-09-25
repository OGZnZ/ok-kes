# Development Guide

## Environment

The project uses Python 3.12; maintenance uses the Miniconda `oknikke` environment.

```powershell
conda activate oknikke
python -m pip install -r requirements.txt --upgrade
python main_debug.py
```

## Tests

```powershell
.\run_tests.ps1
```

You can also run a specific unittest module:

```powershell
python -m unittest tests.TestMain
```

## Docs Site

Install the docs dependencies and start a local preview:

```powershell
python -m pip install -r requirements-docs.txt
python -m mkdocs serve
```

Run a strict build:

```powershell
python -m mkdocs build --strict
```

HTML files are generated in the `site/` directory. After pushing doc-related changes to `master`, GitHub Actions builds and publishes GitHub Pages.

## Building the App

Current official releases are built with GitHub Actions. The historical packaging notes are kept in [`BUILD.md`](https://github.com/baoxin1100/ok-kes/blob/master/BUILD.md) at the repo root.

## Project Design

Task modules, config sync, page handlers, and runtime notes are described in the [software requirements and design](../srd.md).

## Submitting Changes

- Keep the change scope clear; do not mix in logs, caches, personal configs, or unrelated generated files.
- When changing recognition logic, note the affected page, recognition region, thresholds, and test assets.
- When changing user-visible behavior, add screenshots, logs, or clear reproduction steps.
- Run the relevant tests before submitting a PR, and report the results in the PR description.
