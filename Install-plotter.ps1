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

$DEFAULT_BLADEBIT_VERSION = "v3.1.0"
$DEFAULT_MADMAX_VERSION = "0.0.2"
$VERSION = $v
$OS = "windows"
$ARCH = "x86-64"

if (("$plotter" -ne "bladebit") -And ("$plotter" -ne "madmax"))
{
    Write-Output "Plotter must be 'bladebit' or 'madmax'"
    Exit 1
}

# Check for necessary tools
if (!(Get-Command Invoke-WebRequest -errorAction SilentlyContinue)) {
    Write-Output "ERROR: Invoke-WebRequest could not be found. Please ensure PowerShell is updated and try again."
    Exit 1
}

if (!(Get-Command Expand-Archive -errorAction SilentlyContinue)) {
    Write-Output "ERROR: Expand-Archive could not be found. Please ensure PowerShell is updated and try again."
    Exit 1
}

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

function Get-BladebitFilename()
{
    param(
        [string]$ver,
        [string]$os,
        [string]$arch
    )

    "bladebit-${ver}-${os}-${arch}.zip"
}

function Get-BladebitCudaFilename()
{
    param(
        [string]$ver,
        [string]$os,
        [string]$arch
    )

    "bladebit-cuda-${ver}-${os}-${arch}.zip"
}


function Get-BladebitUrl()
{
    param(
        [string]$ver,
        [string]$os,
        [string]$arch
    )

    $GITHUB_BASE_URL = "https://github.com/Chia-Network/bladebit/releases/download"
    $filename = Get-BladebitFilename -ver $ver -os $os -arch $arch

    "${GITHUB_BASE_URL}/${ver}/${filename}"
}

function Get-BladebitCudaUrl()
{
    param(
        [string]$ver,
        [string]$os,
        [string]$arch
    )

    $GITHUB_BASE_URL = "https://github.com/Chia-Network/bladebit/releases/download"
    $filename = Get-BladebitCudaFilename -ver $ver -os $os -arch $arch

    "${GITHUB_BASE_URL}/${ver}/${filename}"
}

function Get-MadmaxFilename()
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

function Get-MadmaxUrl()
{
    param(
        [string]$ksize,
        [string]$ver,
        [string]$os,
        [string]$arch
    )

    $GITHUB_BASE_URL = "https://github.com/Chia-Network/chia-plotter-madmax/releases/download"
    $madmax_filename = Get-MadmaxFilename -ksize $ksize -ver $ver -os $os -arch $arch

    "${GITHUB_BASE_URL}/${ver}/${madmax_filename}"
}

# Function to download, extract, set permissions, and clean up
function Get-Binary()
{
    param(
        [string]$url,
        [string]$dest_dir,
        [string]$new_filename
    )

    $filename = [System.IO.Path]::GetFileName($url)
    $download_path = Join-Path -Path $PWD -ChildPath $filename
    try {
        Invoke-WebRequest -Uri $url -OutFile $download_path
    } catch {
        Write-Warning "Failed to download from ${url}. Maybe specified version of the binary does not exist."
        return
    }

    $extension = [System.IO.Path]::GetExtension($download_path)
    if ($extension -eq '.zip') {
        Expand-Archive -Path $download_path -DestinationPath $dest_dir -Force
        Remove-Item -Path $download_path
    } else {
        Move-Item -Path $download_path -Destination (Join-Path -Path $dest_dir -ChildPath $filename) -Force
    }

    # Check if new_filename parameter is provided
    if ($new_filename) {
        # Construct the full paths to the old and new files
        $old_file_path = Join-Path -Path $dest_dir -ChildPath $filename
        $new_file_path = Join-Path -Path $dest_dir -ChildPath $new_filename
        # If the new file already exists, delete it
        if (Test-Path $new_file_path) {
            Remove-Item -Path $new_file_path
        }
        # Rename the old file to the new filename
        Rename-Item -Path $old_file_path -NewName $new_file_path
    }

    Write-Output "Successfully installed $filename to $dest_dir"
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

        $url = Get-BladebitUrl -ver $version -os $os -arch $arch
        $dest_dir = $PWD
        Get-Binary -url $url -dest_dir $dest_dir

        $url = Get-BladebitCudaUrl -ver $version -os $os -arch $arch
        $dest_dir = $PWD
        Get-Binary -url $url -dest_dir $dest_dir
    }
    elseif("${plotter}" -eq "madmax")
    {
        if (-not($VERSION))
        {
            $VERSION = $DEFAULT_MADMAX_VERSION
        }

        Write-Output "Installing madmax ${VERSION}"

        $url = Get-MadmaxUrl -ksize "k32" -ver $version -os $os -arch $arch
        $dest_dir = $PWD
        Get-Binary -url $url -dest_dir $dest_dir -new_filename "chia_plot_k32.exe"

        $url = Get-MadmaxUrl -ksize "k34" -ver $version -os $os -arch $arch
        $dest_dir = $PWD
        Get-Binary -url $url -dest_dir $dest_dir -new_filename "chia_plot_k34.exe"
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
