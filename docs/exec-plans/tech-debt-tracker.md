# Tech Debt Tracker

Severity: **High** / **Medium** / **Low**

---

## Active debt

### [Medium] CHANGELOG.md incomplete
`CHANGELOG.md` only documents `0.1.0`. Versions `0.2.x` and `0.3.0` are undocumented.

**Next action:** Reconstruct from git log and add entries for each version bump.

---

### [Medium] No CI/CD pipeline
There are no GitHub Actions workflows or other CI configuration. Tests run manually only.

**Next action:** Add `.github/workflows/ci.yml` with `pytest tests/`, lint, and a build check. At minimum, run `pytest` on push to `main`.

---

### [Medium] `setup.py` diverges from `pyproject.toml`
`setup.py` is missing `tenacity>=8.0` and `requests>=2.25` from its `install_requires`. Using both files risks inconsistent installs depending on the build frontend.

**Next action:** Either remove `setup.py` entirely (modern pip + `pyproject.toml` is sufficient) or sync the dependency lists.

---

### [Low] `prepare_grid()` docstring says "устаревший" (deprecated) but no deprecation warning
The method is marked deprecated in its docstring but does not emit a `DeprecationWarning` at runtime.

**Next action:** Add `warnings.warn("prepare_grid() is deprecated, use Grid.from_name()", DeprecationWarning, stacklevel=2)` at the top of the function.

---

### [Low] Tools in `tools/` are not part of the public API but live inside the package
CLI/GUI tools (`telemetry_reader_gui.py`, `blueprint_editor.py`, etc.) are importable as `secontrol.tools.*` but are not listed in `__all__` and have no documented interface.

**Next action:** Either expose them as `entry_points` console scripts in `pyproject.toml`, or move them to a top-level `tools/` directory outside `src/`.

---

### [Low] `device_types.py` is described as legacy compatibility wrapper
File exists solely to re-export from elsewhere. If nothing imports it externally it can be removed.

**Next action:** Grep for external usage; remove if safe.

---

## Resolved debt

*(none yet — add entries here as debt is paid down)*
