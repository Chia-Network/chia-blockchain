$ErrorActionPreference = "Stop"

if ([Environment]::Is64BitOperatingSystem -eq $false)
{
    Write-Host "Chia requires a 64-bit Windows installation"
    Exit 1
}

if ((Get-Item "$env:windir\System32\msvcp140.dll").Exists -eq $false)
{
    Write-Host "Unable to find Visual C++ Runtime DLLs"
    Write-Host ""
    Write-Host "Download and install the Visual C++ Redistributable for Visual Studio 2019 package from:"
    Write-Host "https://visualstudio.microsoft.com/downloads/#microsoft-visual-c-redistributable-for-visual-studio-2019"
    Exit 1
}

if ((Get-Command git -ErrorAction SilentlyContinue) -eq $null)
{
    Write-Host "Unable to find git"
    Exit 1
}

git submodule update --init mozilla-ca

if ((Get-Command py -ErrorAction SilentlyContinue) -eq $null)
{
    Write-Host "Unable to find py"
    Exit 1
}

$pythonVersion = (py --version).split(" ")[1]
if ([version]$pythonVersion -lt [version]"3.7.0")
{
    Write-Host "Installation requires Python 3.7 or later"
    Exit 1
}
Write-Host "Python version is:" $pythonVersion

py -m venv venv
.\venv\Scripts\Activate.ps1

py -m pip install pip --upgrade
pip install --upgrade setuptools
pip install --upgrade wheel
pip install --extra-index-url https://pypi.chia.net/simple/ miniupnpc==2.2.2
pip install --editable . --extra-index-url https://pypi.chia.net/simple/

Write-Host ""
Write-Host "Chia blockchain .\Install.ps1 complete."
Write-Host "For assistance join us on Keybase in the #support chat channel:"
Write-Host "https://keybase.io/team/chia_network.public"
Write-Host ""
Write-Host "Try the Quick Start Guide to running chia-blockchain:"
Write-Host "https://github.com/Chia-Network/chia-blockchain/wiki/Quick-Start-Guide"
Write-Host ""
Write-Host "To install the GUI type '.\Install-gui.ps1' after '.\venv\scripts\Activate.ps1'."
Write-Host ""
Write-Host "Type '.\venv\Scripts\Activate.ps1' and then 'chia init' to begin."
