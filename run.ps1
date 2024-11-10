# Create venv if it doesn't exist
if (-not (Test-Path "venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    python -m venv venv
}

# Activate venv and install requirements if needed
Write-Host "Activating virtual environment..." -ForegroundColor Yellow
.\venv\Scripts\Activate.ps1

# Check if requirements are installed
if (-not (Test-Path "venv\Lib\site-packages\click")) {
    Write-Host "Installing requirements..." -ForegroundColor Yellow
    pip install -r requirements.txt
}

# Run srv.py in interactive mode
Write-Host "Starting SRV in interactive mode..." -ForegroundColor Green
python srv.py interactive 