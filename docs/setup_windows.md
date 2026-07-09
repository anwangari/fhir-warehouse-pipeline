# Local dev setup — Windows

> **Windows is for development only. Deployment target is Linux.**
> The code, `docker-compose.yml`, and SQL are cross-platform; only the
> shell commands and a few tooling steps differ. Commands below are for
> **PowerShell** (the default terminal on Windows 10/11).

## Prerequisites (install once)

Using [winget](https://learn.microsoft.com/windows/package-manager/) (built into Windows 11 / recent Windows 10):

```powershell
winget install Python.Python.3.12
winget install EclipseAdoptium.Temurin.17.JDK   # Java for Synthea (11+ works)
winget install Docker.DockerDesktop             # then launch Docker Desktop once
winget install Git.Git
```

Verify:

```powershell
python --version
java -version
docker --version
```

> Docker Desktop must be **running** before `docker compose` works.
> On first launch it may prompt to enable WSL2 — accept it.

## 1. Python virtual environment

```powershell
# from the repo root
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If activation is blocked by execution policy, allow it for this session only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

(`.venv\` is already covered by `.gitignore`.)

## 2. Start Postgres

```powershell
docker compose up -d
docker compose ps          # STATUS should show "healthy"
```

Connect with psql *inside* the container (no local psql install needed):

```powershell
docker exec -it fhir_dw_postgres psql -U fhir -d fhir_dw
```

To stop it later: `docker compose down` (add `-v` to also wipe the data volume).

## 3. Generate data

**Synthea (primary path):**

```powershell
# download the jar once — use curl.exe (the real curl, not the PowerShell alias)
curl.exe -L -o synthea-with-dependencies.jar `
  https://github.com/synthetichealth/synthea/releases/download/master-branch-latest/synthea-with-dependencies.jar

# generate ~50 patients into .\data
java -jar synthea-with-dependencies.jar `
  -p 50 `
  --exporter.fhir.export true `
  --exporter.fhir.use_us_core_ig true `
  --exporter.baseDirectory .\data `
  Massachusetts
```

> PowerShell uses a backtick (`` ` ``) for line continuation, not `\`.
> If `curl.exe` isn't found, use `Invoke-WebRequest -Uri <url> -OutFile synthea-with-dependencies.jar`.

**Offline fixtures (fallback):**

```powershell
python scripts\generate_sample_bundles.py --patients 10 --out data\fhir
```

## 4. Run the pipeline (later days)

```powershell
python run.py        # parse -> load -> dq
pytest -q            # tests
```

## Windows → Linux gotchas (already handled / worth knowing)

- **Line endings:** `.gitattributes` forces `LF` for code/SQL/shell so files
  authored on Windows run correctly on the Linux deploy target. Don't override it.
- **Path separators:** the Python code uses `pathlib` / `os.path`, so
  `data/fhir` works on both. Avoid hardcoding `\` in any new code.
- **Env/secrets:** put local config in `.env` (gitignored). AWS creds come
  from `%USERPROFILE%\.aws\credentials` (the Windows equivalent of `~/.aws`)
  or environment variables — never in code.
- **Docker volume:** the `pgdata` volume lives inside Docker Desktop's WSL2
  VM, not your repo, so it won't clutter the working tree.
