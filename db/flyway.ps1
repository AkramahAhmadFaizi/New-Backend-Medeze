# Runs Flyway in Docker against the database in .env.flyway.
# Usage (from the project folder):
#   .\db\flyway.ps1 info
#   .\db\flyway.ps1 validate
#   .\db\flyway.ps1 migrate
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root ".env.flyway"
if (-not (Test-Path $envFile)) { throw "Missing .env.flyway - copy .env.flyway.example and fill it in." }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "Docker not found. Install/start Docker Desktop." }

$migrations = Join-Path $root "db\migrations"

docker run --rm `
  --env-file $envFile `
  -v "${migrations}:/flyway/sql:ro" `
  redgate/flyway `
  -locations=filesystem:/flyway/sql `
  -schemas=flyway `
  -defaultSchema=flyway `
  -cleanDisabled=true `
  @args