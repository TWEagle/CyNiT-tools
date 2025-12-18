# CyNiT Tools – Enterprise requirements layout

This folder is the **single source of truth** for dependencies.

## Files
- `*.in` are **human-edited** inputs (high-level deps).
- `lock/*.txt` are **generated** lockfiles (exact resolved versions).

## Typical flows

### New PC (Windows)
```powershell
scripts\bootstrap.ps1
scripts\compile-locks.ps1    # optional if you already committed lockfiles
scripts\install-dev.ps1
scripts\RUN_CYNiT.ps1
```

### Add a dependency
1) Add it to the right `requirements/*.in`
2) Recompile:
```powershell
scripts\compile-locks.ps1
```
3) Commit changes in `requirements/` (including `lock/`)

## Why lockfiles?
Because they make installs reproducible and stop “missing module roulette”.
