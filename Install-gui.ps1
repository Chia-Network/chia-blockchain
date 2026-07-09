$ErrorActionPreference = "Stop"
$SUBMODULE_BRANCH = $args[0]

if ($null -eq (Get-ChildItem env:VIRTUAL_ENV -ErrorAction SilentlyContinue))
{
    Write-Output "This script requires that the Chia Python virtual environment is activated."
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
if ( $SUBMODULE_BRANCH ) {
  git fetch --all
  git reset --hard $SUBMODULE_BRANCH
  Write-Output ""
  Write-Output "Building the GUI with branch $SUBMODULE_BRANCH"
  Write-Output ""
}


Push-Location
try {
    Set-Location chia-blockchain-gui

    $ErrorActionPreference = "SilentlyContinue"
    npm ci --loglevel=error
    npm audit fix

    # Work around Electron's postinstall being silently skipped in the workspaces/
    # hoisted install, which leaves node_modules/electron present but without its
    # platform binary (no path.txt). Re-run Electron's own installer if needed.
    # Otherwise 'npm run electron' fails with "Electron failed to install correctly".
    if (-not (Test-Path "node_modules/electron/path.txt")) {
        Write-Output "Electron binary is missing; running Electron's install script."
        node node_modules/electron/install.js
    }

    npm run build
    py ..\installhelper.py

    Write-Output ""
    Write-Output "Chia blockchain Install-gui.ps1 completed."
    Write-Output ""
    Write-Output "Type 'cd chia-blockchain-gui' and then 'npm run electron' to start the GUI."
} finally {
    Pop-Location
}
