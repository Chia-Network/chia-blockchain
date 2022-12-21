<#
.DESCRIPTION
    Install plotter binary
.PARAMETER v
    The version of plotter to install
.EXAMPLES
    PS> .\install-plotter.ps1 bladebit -v v2.0.0-beta1
    PS> .\install-plotter.ps1 madmax
#>
param(
    [parameter(Position=0, Mandatory=$True, HelpMessage="'bladebit' or 'madmax'")]
    [string]$plotter,
    [parameter(HelpMessage="Specify the version of plotter to install")]
    [string]$v
)

$ErrorActionPreference = "Stop"

if (("$plotter" -ne "bladebit") -And ("$plotter" -ne "madmax"))
{
    Write-Output "Plotter must be 'bladebit' or 'madmax'"
    Exit 1
}

function get_bladebit_filename()
{
    param(
        [string]$ver,
        [string]$os,
        [string]$arch
    )

    "bladebit-${ver}-${os}-${arch}.zip"
}

function get_bladebit_url()
{
    param(
        [string]$ver,
        [string]$os,
        [string]$arch
    )

    $GITHUB_BASE_URL = "https://github.com/Chia-Network/bladebit/releases/download"
    $filename = get_bladebit_filename -ver $ver -os $os -arch $arch

    "${GITHUB_BASE_URL}/${ver}/${filename}"
}

function get_madmax_filename()
{
    param(
        [string]$ksize,
        [string]$ver,
        [string]$os,
        [string]$arch
    )

    $chia_plot = "chia_plot"
    if ("${ksize}" -eq "k34")
    {
        $chia_plot = "chia_plot_k34"
    }
    $suffix = ""
    if ("${os}" -eq "macos")
    {
        $suffix = "-${os}-${arch}"
    }
    elseif("${os}" -eq "windows")
    {
        $suffix = ".exe"
    }
    else
    {
        $suffix = "-${arch}"
    }

    "${chia_plot}-${ver}${suffix}"
}

function get_madmax_url()
{
    param(
        [string]$ksize,
        [string]$ver,
        [string]$os,
        [string]$arch
    )

    $GITHUB_BASE_URL = "https://github.com/Chia-Network/chia-plotter-madmax/releases/download"
    $madmax_filename = get_madmax_filename -ksize $ksize -ver $ver -os $os -arch $arch

    "${GITHUB_BASE_URL}/${ver}/${madmax_filename}"
}

$DEFAULT_BLADEBIT_VERSION = "v2.0.0"
$DEFAULT_MADMAX_VERSION = "0.0.2"
$VERSION = $v
$OS = "windows"
$ARCH = "x86-64"


if ($null -eq (Get-ChildItem env:VIRTUAL_ENV -ErrorAction SilentlyContinue))
{
    Write-Output "This script requires that the Chia Python virtual environment is activated."
    Write-Output "Execute '.\venv\Scripts\Activate.ps1' before running."
    Exit 1
}

$venv_bin = "${env:VIRTUAL_ENV}\Scripts"
if (-not (Test-Path -Path "$venv_bin" -PathType Container))
{
    Write-Output "ERROR: venv folder does not exists: '${venv_bin}'"
    Exit 1
}

Push-Location
try {
    Set-Location "${venv_bin}"
    $ErrorActionPreference = "SilentlyContinue"

    if ("${plotter}" -eq "bladebit")
    {
        if (-not($VERSION))
        {
            $VERSION = $DEFAULT_BLADEBIT_VERSION
        }

        Write-Output "Installing bladebit ${VERSION}"

        $URL = get_bladebit_url -ver "${VERSION}" -os "${OS}" -arch "${ARCH}"
        Write-Output "Fetching binary from: ${URL}"
        try {
            Invoke-WebRequest -Uri "$URL" -OutFile ".\bladebit.zip"
            Write-Output "Successfully downloaded: $URL"
        }
        catch {
            Write-Output "ERROR: Download failed. Maybe specified version of the binary does not exist."
            Pop-Location
            Exit 1
        }

        Expand-Archive -Path ".\bladebit.zip" -DestinationPath ".\bladebit"
        Move-Item .\bladebit\bladebit.exe .\ -Force
        Remove-Item bladebit -Force
        Remove-Item bladebit.zip -Force
        Write-Output "Successfully installed bladebit to $(Get-Location)\bladebit.exe"
    }
    elseif("${plotter}" -eq "madmax")
    {
        if (-not($VERSION))
        {
            $VERSION = $DEFAULT_MADMAX_VERSION
        }

        Write-Output "Installing madmax ${VERSION}"

        $madmax_filename = get_madmax_filename -ksize k32 -ver "${VERSION}" -os "${OS}" -arch "${ARCH}"
        $URL = get_madmax_url -ksize k32 -ver "${VERSION}" -os "${OS}" -arch "${ARCH}"
        Write-Output "Fetching binary from: ${URL}"
        try {
            Invoke-WebRequest -Uri "$URL" -Outfile "chia_plot.exe"
            Write-Output "Successfully downloaded: $URL"
            Write-Output "Successfully installed madmax to $(Get-Location)\chia_plot.exe"
        }
        catch {
            Write-Output "ERROR: Download failed. Maybe specified version of the binary does not exist."
            Pop-Location
            Exit 1
        }

        $madmax_filename = get_madmax_filename -ksize k34 -ver "${VERSION}" -os "${OS}" -arch "${ARCH}"
        $URL = get_madmax_url -ksize k34 -ver "${VERSION}" -os "${OS}" -arch "${ARCH}"
        Write-Output "Fetching binary from: ${URL}"
        try {
            Invoke-WebRequest -Uri "$URL" -Outfile "chia_plot_k34.exe"
            Write-Output "Successfully downloaded: $URL"
            Write-Output "Successfully installed madmax for k34 to $(Get-Location)\chia_plot_k34.exe"
        }
        catch {
            Write-Output "madmax for k34 is not found"
        }
    }
    else
    {
        Write-Output "Only 'bladebit' and 'madmax' are supported"
    }
}
catch {
    Write-Output "An error occurred:"
    Write-Output $_
}
finally {
    Pop-Location
}
