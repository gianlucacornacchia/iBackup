## Summary

<!-- What changes and why. Link the issue if there is one. -->

## Checklist

- [ ] `ruff check .` and `ruff format --check .` pass
- [ ] `mypy --strict src/iphone_archive/core src/iphone_archive/catalog` passes
- [ ] `pytest` passes (with `QT_QPA_PLATFORM=offscreen`)
- [ ] Tests were added or updated for the change
- [ ] The affected docs are updated in the same commit, including a `docs/progress.md` entry
- [ ] Any new capability is available in both the CLI and the GUI
