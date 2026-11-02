# Contributing

Keep changes focused on reliable, understandable file-content verification.
Use fictional or generated sample files when reporting an issue; do not attach
real evidence, private baselines, or reports containing identifying paths.

## Local setup

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

On Windows PowerShell, use `py -3 -m venv .venv`, then
`.\.venv\Scripts\python.exe -m pip install -e '.[dev]'`. In the checks below,
replace `python` with `.\.venv\Scripts\python.exe` and `ruff` with
`.\.venv\Scripts\python.exe -m ruff`; activation is optional.

Before submitting a change:

```sh
ruff check .
ruff format --check .
python -m coverage run -m unittest discover -s tests -v
python -m coverage report
python scripts/demo.py
python -m build
python scripts/smoke_wheel.py
```

The wheel smoke test expects exactly one wheel in `dist/`. Move old version
builds elsewhere before running it. CI uses a fresh checkout for each job.

POSIX named-pipe tests skip on Windows; Windows junction tests skip elsewhere.
Symlink tests skip only if Windows refuses link creation without Developer Mode
or elevation. Ordinary tool usage does not require either privilege.

For a behavior change, add a regression test that would fail before the fix and
update the relevant command or design documentation. Preserve the distinction
between changed content and an incomplete scan. Avoid silently changing the
manifest format or the meaning of saved exclusion patterns.

Include the command, expected result, actual result, Python version, and operating
system in bug reports. Explain the problem and validation in pull requests.
