param(
    [Parameter(HelpMessage="install development dependencies")]
    [switch]$d = $False,
    [Parameter()]
    [switch]$i = $False,
    [Parameter()]
    [switch]$p = $False
)

$ErrorActionPreference = "Stop"

$extras = @()
$extras += "upnp"
if ($d)
{
    $extras += "dev"
}

if ([Environment]::Is64BitOperatingSystem -eq $false)
{
    Write-Output "Chia requires a 64-bit Windows installation"
    Exit 1
}

if (-not (Get-Item -ErrorAction SilentlyContinue "$env:windir\System32\msvcp140.dll").Exists)
{
    Write-Output "Unable to find Visual C++ Runtime DLLs"
    Write-Output ""
    Write-Output "Download and install the Visual C++ Redistributable for Visual Studio 2019 package from:"
    Write-Output "https://visualstudio.microsoft.com/downloads/#microsoft-visual-c-redistributable-for-visual-studio-2019"
    Exit 1
}

if ($null -eq (Get-Command git -ErrorAction SilentlyContinue))
{
    Write-Output "Unable to find git"
    Exit 1
}

git submodule update --init mozilla-ca

if ($null -eq (Get-Command py -ErrorAction SilentlyContinue))
{
    Write-Output "Unable to find py"
    Write-Output "Note the check box during installation of Python to install the Python Launcher for Windows."
    Write-Output ""
    Write-Output "https://docs.python.org/3/using/windows.html#installation-steps"
    Exit 1
}

$supportedPythonVersions = "3.12", "3.11", "3.10", "3.9", "3.8"
if ("$env:INSTALL_PYTHON_VERSION" -ne "")
{
    $pythonVersion = $env:INSTALL_PYTHON_VERSION
}
else
{
    foreach ($version in $supportedPythonVersions)
    {
        try
        {
            py -$version --version 2>&1 >$null
            $result = $?
        }
        catch
        {
            $result = $false
        }
        if ($result)
        {
            $pythonVersion = $version
            break
        }
    }

    if (-not $pythonVersion)
    {
        $reversedPythonVersions = $supportedPythonVersions.clone()
        [array]::Reverse($reversedPythonVersions)
        $reversedPythonVersions = $reversedPythonVersions -join ", "
        Write-Output "No usable Python version found, supported versions are: $reversedPythonVersions"
        Exit 1
    }
}

$fullPythonVersion = (py -$pythonVersion --version).split(" ")[1]

Write-Output "Python version is: $fullPythonVersion"

$openSSLVersionStr = (py -$pythonVersion -c 'import ssl; print(ssl.OPENSSL_VERSION)')
$openSSLVersion = (py -$pythonVersion -c 'import ssl; print(ssl.OPENSSL_VERSION_NUMBER)')
if ($openSSLVersion -lt 269488367)
{
    Write-Output "Found Python with OpenSSL version:" $openSSLVersionStr
    Write-Output "Anything before 1.1.1n is vulnerable to CVE-2022-0778."
}

$extras_cli = @()
foreach ($extra in $extras)
{
    $extras_cli += "--extras"
    $extras_cli += $extra
}

./Setup-poetry.ps1 -pythonVersion "$pythonVersion"
.penv/Scripts/poetry env use $(py -"$pythonVersion" -c 'import sys; print(sys.executable)')
.penv/Scripts/poetry install @extras_cli

if ($i)
{
    Write-Output "Running 'pip install --no-deps .' for non-editable"
    .venv/Scripts/python -m pip install --no-deps .
}

if ($p)
{
    $PREV_VIRTUAL_ENV = "$env:VIRTUAL_ENV"
    $env:VIRTUAL_ENV = ".venv"
    .\Install-plotter.ps1 bladebit
    .\Install-plotter.ps1 madmax
    $env:VIRTUAL_ENV = "$PREV_VIRTUAL_ENV"
}

cmd /c mklink /j venv .venv

Write-Output ""
Write-Output "Chia blockchain .\Install.ps1 complete."
Write-Output "For assistance join us on Discord in the #support chat channel:"
Write-Output "https://discord.gg/chia"
Write-Output ""
Write-Output "Try the Quick Start Guide to running chia-blockchain:"
Write-Output "https://docs.chia.net/introduction"
Write-Output ""
Write-Output "To install the GUI run '.\.venv\scripts\Activate.ps1' then '.\Install-gui.ps1'."
Write-Output ""
Write-Output "Type '.\.venv\Scripts\Activate.ps1' and then 'chia init' to begin."
