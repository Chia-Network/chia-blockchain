param(
    [Parameter(HelpMessage="install development dependencies")]
    [switch]$d = $False,
    [Parameter()]
    [switch]$p = $False
)

$ErrorActionPreference = "Stop"

$extras = @()
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

$supportedPythonVersions = "3.10", "3.9", "3.8", "3.7"
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

if ($extras.length -gt 0)
{
    $extras_cli = $extras -join ","
    $extras_cli = "[$extras_cli]"
}
else
{
    $extras_cli = ""
}

py -$pythonVersion -m venv venv

venv\scripts\python -m pip install --upgrade pip setuptools wheel
venv\scripts\pip install --extra-index-url https://pypi.chia.net/simple/ miniupnpc==2.2.2
venv\scripts\pip install --editable ".$extras_cli" --extra-index-url https://pypi.chia.net/simple/

if ($p)
{
    $PREV_VIRTUAL_ENV = "$env:VIRTUAL_ENV"
    $env:VIRTUAL_ENV = "venv"
    .\Install-plotter.ps1 bladebit
    .\Install-plotter.ps1 madmax
    $env:VIRTUAL_ENV = "$PREV_VIRTUAL_ENV"
}

Write-Output ""
Write-Output "Chia blockchain .\Install.ps1 complete."
Write-Output "For assistance join us on Keybase in the #support chat channel:"
Write-Output "https://keybase.io/team/chia_network.public"
Write-Output ""
Write-Output "Try the Quick Start Guide to running chia-blockchain:"
Write-Output "https://github.com/Chia-Network/chia-blockchain/wiki/Quick-Start-Guide"
Write-Output ""
Write-Output "To install the GUI type '.\Install-gui.ps1' after '.\venv\scripts\Activate.ps1'."
Write-Output ""
Write-Output "Type '.\venv\Scripts\Activate.ps1' and then 'chia init' to begin."
