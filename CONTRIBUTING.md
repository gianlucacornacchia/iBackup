# Contributing

Thanks for your interest in iPhone Archive. Bug reports, device compatibility
reports and pull requests are all welcome.

## Reporting a problem

Open an [issue](https://github.com/gianlucacornacchia/iBackup/issues/new/choose)
and include your Windows version, iPhone model and iOS version, the command or
GUI action you ran, and the relevant log lines from `<archive>\.ibackup\logs\`.
Do not attach personal photos, or a `catalog.sqlite` or `Photos.sqlite` that
holds your own data.

## Development setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pre-commit install
```

Full details are in [docs/development.md](docs/development.md).

## Before opening a pull request

Run the same checks CI runs:

```powershell
ruff check .
ruff format --check .
mypy --strict src/iphone_archive/core src/iphone_archive/catalog
$env:QT_QPA_PLATFORM = "offscreen"; pytest
```

Also:

- **Keep the layering.** `cli.py` and `gui/` only call the `service/` layer,
  and every capability must be reachable from both. `tests/test_gui_parity.py`
  enforces this.
- **Never weaken the safety model.** Imports must not modify archived files,
  and permanent deletions must keep their typed-`DELETE` confirmation (see
  [specification §13](docs/specifications.md)).
- **Update the docs in the same commit** as the behaviour they describe. The
  table in [AGENTS.md](AGENTS.md) lists which doc covers what, and every change
  gets a dated entry in [docs/progress.md](docs/progress.md).
- **Use [Conventional Commits](https://www.conventionalcommits.org/)** (`feat:`,
  `fix:`, `docs:`, `test:`, `chore:`, …), one logical change per commit.
- **Record significant decisions** as an ADR in [docs/adr/](docs/adr/README.md).

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).
