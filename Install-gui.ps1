#$ErrorActionPreference = "Stop"

if ((Get-ChildItem env:VIRTUAL_ENV -ErrorAction SilentlyContinue) -eq $null)
{
    Write-Host "This requires the chia python virtual environment."
    Write-Host "Execute '.\venv\Scripts\Activate.ps1' before running."
    Exit 1
}

if ((Get-Command node -ErrorAction SilentlyContinue) -eq $null)
{
    Write-Host "Unable to find Node.js"
    Exit 1
}

Write-Host "Running git submodule update --init --recursive."
Write-Host ""
git submodule update --init --recursive
Write-Host "Running git submodule update."
Write-Host ""
git submodule update
cd chia-blockchain-gui

$ErrorActionPreference = "SilentlyContinue"
npm install --loglevel=error
npm audit fix
npm run build
py ..\installhelper.py

Write-Host ""
Write-Host "Chia blockchain install-gui.sh completed."
Write-Host ""
Write-Host "Type 'cd chia-blockchain-gui' and then 'npm run electron' to start the GUI."