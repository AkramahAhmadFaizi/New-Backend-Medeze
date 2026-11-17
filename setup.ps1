# One-time setup. Run from the therapy-backend folder in VS Code's terminal:
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env - now fill in your Supabase URL and secret key." }
Write-Host "Done. Activate with:  .\.venv\Scripts\Activate.ps1"
