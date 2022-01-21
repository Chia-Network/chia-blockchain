$ErrorActionPreference = "Stop"

if ($null -eq (Get-ChildItem env:VIRTUAL_ENV -ErrorAction SilentlyContinue))
{
    Write-Output "This script requires that the Chinilla Python virtual environment is activated."
    Write-Output "Execute '.\venv\Scripts\Activate.ps1' before running."
    Exit 1
}

if ($null -eq (Get-Command node -ErrorAction SilentlyContinue))
{
    Write-Output "Unable to find Node.js"
    Exit 1
}

Write-Output "Running 'git submodule update --init --recursive'."
Write-Output ""
git submodule update --init --recursive

Push-Location
try {
    Set-Location chinilla-blockchain-gui

    $ErrorActionPreference = "SilentlyContinue"
    npm ci --loglevel=error
    npm audit fix
    npm run build
    py ..\installhelper.py

    Write-Output ""
    Write-Output "Chinilla blockchain Install-gui.ps1 completed."
    Write-Output ""
    Write-Output "Type 'cd chinilla-blockchain-gui' and then 'npm run electron' to start the GUI."
} finally {
    Pop-Location
}
