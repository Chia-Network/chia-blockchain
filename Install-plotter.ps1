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
        [string]$bladebit_ver,
        [string]$os,
        [string]$arch
    )

    "bladebit-${bladebit_ver}-${os}-${arch}.zip"
}

function get_bladebit_url()
{
    param(
        [string]$bladebit_ver,
        [string]$os,
        [string]$arch
    )

    $GITHUB_BASE_URL = "https://github.com/Chia-Network/bladebit/releases/download"
    $filename = get_bladebit_filename $bladebit_ver $os $arch

    "${GITHUB_BASE_URL}/${bladebit_ver}/${filename}"
}

function get_madmax_filename()
{
    param(
        [string]$ksize,
        [string]$madmax_ver,
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

    "${chia_plot}-${madmax_ver}${suffix}"
}

function get_madmax_url()
{
    param(
        [string]$ksize,
        [string]$madmax_ver,
        [string]$os,
        [string]$arch
    )

    $GITHUB_BASE_URL = "https://github.com/Chia-Network/chia-plotter-madmax/releases/download"
    $madmax_filename = get_madmax_filename $ksize $madmax_ver $os $arch

    "${GITHUB_BASE_URL}/${madmax_ver}/${madmax_filename}"
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

        $URL = get_bladebit_url "${VERSION}" "${OS}" "${ARCH}"
        Write-Output "Fetching binary from: ${URL}"
        Invoke-WebRequest -Uri "$URL" -OutFile ".\bladebit.zip"
        Expand-Archive -Path ".\bladebit.zip" -DestinationPath ".\bladebit"
        Move-Item .\bladebit\bladebit.exe .\
        Remove-Item bladebit -Force
    }
    elseif("${plotter}" -eq "madmax")
    {
        if (-not($VERSION))
        {
            $VERSION = $DEFAULT_MADMAX_VERSION
        }

        Write-Output "Installing madmax ${VERSION}"

        $madmax_filename = get_madmax_filename k32 "${VERSION}" "${OS}" "${ARCH}"
        $URL = get_madmax_url k32 "${VERSION}" "${OS}" "${ARCH}"
        Write-Output "Fetching binary from: ${URL}"
        Invoke-WebRequest -Uri "$URL" -Outfile "${madmax_filename}"

        $madmax_filename = get_madmax_filename k34 "${VERSION}" "${OS}" "${ARCH}"
        $URL = get_madmax_url k34 "${VERSION}" "${OS}" "${ARCH}"
        Write-Output "Fetching binary from: ${URL}"
        Invoke-WebRequest -Uri "$URL" -Outfile "${madmax_filename}"
    }
    else
    {
        Write-Output "Only 'bladebit' and 'madmax' are supported"
    }
} finally {
    Pop-Location
}
