# dev_env

This folder contains the repository items and environment definitions needed to build local developer environments.

## Included environments

- `openjdk17`
  - `Containerfile`
  - `podman-compose.yml`
- `experience`
  - `Containerfile`
  - `podman-compose.yml`
- `plsql-python`
  - `Containerfile`
  - `podman-compose.yml`
  - `requirements/` for optional Python dependency groups
- `ellucian-experience`
  - `Containerfile`
  - `podman-compose.yml`
  - `.gitignore`

## GitHub build automation

A GitHub Actions workflow exists at `.github/workflows/build-dev-env.yml`.

It automatically builds the supported dev environment container images when changes are made under `dev_env/`.

## Local build helper

Use the local helper script to build all environments from this folder:

```powershell
pwsh ./dev_env/scripts/build-dev-env.ps1
```

For a single environment:

```powershell
pwsh ./dev_env/scripts/build-dev-env.ps1 -Env openjdk17
```

## Notes

- `plsql-python` requires an `oracle-client/` directory with Oracle Instant Client ZIPs before build.
- These definitions are intentionally self-contained and reproducible.
