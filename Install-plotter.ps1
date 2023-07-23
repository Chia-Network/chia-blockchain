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

# Function to download, extract, set permissions, and clean up
function Handle-Binary {
    param(
        [string]$Url,
        [string]$Filename,
        [string]$BinaryName,
        [string]$NewBinaryName
    )

    Write-Output "Fetching binary from: ${Url}"
    try {
        Invoke-WebRequest -Uri "$Url" -OutFile "$Filename"
        Write-Output "Successfully downloaded: $Url"
        if ($Filename -like "*.zip") {
            Expand-Archive -Path "$Filename" -DestinationPath ".\$BinaryName"
            Write-Output "Successfully extracted ${BinaryName} to $(Get-Location)\${BinaryName}"
        }
        elseif ($NewBinaryName) {
            Rename-Item -Path "$Filename" -NewName "$NewBinaryName"
            Write-Output "Successfully renamed ${BinaryName} to ${NewBinaryName}"
        }
        else {
            Write-Output "Successfully installed ${BinaryName} to $(Get-Location)\${BinaryName}"
        }
    } catch {
        Write-Output "WARNING: Failed to download from ${Url}. Maybe specified version of the binary does not exist."
    }
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

if ($null -eq (Get-ChildItem env:VIRTUAL_ENV -ErrorAction SilentlyContinue)) {
    Write-Output "This script requires that the Chia Python virtual environment is activated."
    Write-Output "Execute '.\\venv\\Scripts\\Activate.ps1' before running."
    Exit 1
}

$venv_bin = "${env:VIRTUAL_ENV}\\Scripts"
if (-not (Test-Path -Path "$venv_bin" -PathType Container)) {
    Write-Output "ERROR: venv folder does not exists: '${venv_bin}'"
    Exit 1
}

$DEFAULT_BLADEBIT_VERSION = "v2.0.0"
$DEFAULT_MADMAX_VERSION = "0.0.2"
$VERSION = $v
$OS = "windows"
$ARCH = "x86-64"

Push-Location
try {
    Set-Location "${venv_bin}"
    $ErrorActionPreference = "SilentlyContinue"

    if ("${plotter}" -eq "bladebit") {
        if (-not($VERSION)) {
            $VERSION = $DEFAULT_BLADEBIT_VERSION
        }

        Write-Output "Installing bladebit ${VERSION}"

        $URL = get_bladebit_url -ver "${VERSION}" -os "${OS}" -arch "${ARCH}"
        $bladebitFilename = get_bladebit_filename -ver "${VERSION}" -os "${OS}" -arch "${ARCH}"
        Handle-Binary -Url $URL -Filename $bladebitFilename -BinaryName "bladebit"
    }
    elseif("${plotter}" -eq "madmax") {
        if (-not($VERSION)) {
            $VERSION = $DEFAULT_MADMAX_VERSION
        }

        Write-Output "Installing madmax ${VERSION}"

        $URL = get_madmax_url -ksize k32 -ver "${VERSION}" -os "${OS}" -arch "${ARCH}"
        $madmaxFilename = get_madmax_filename -ksize k32 -ver "${VERSION}" -os "${OS}" -arch "${ARCH}"
        Handle-Binary -Url $URL -Filename $madmaxFilename -BinaryName "chia_plot" -NewBinaryName "chia_plot_k32.exe"

        $URL = get_madmax_url -ksize k34 -ver "${VERSION}" -os "${OS}" -arch "${ARCH}"
        $madmaxFilename = get_madmax_filename -ksize k34 -ver "${VERSION}" -os "${OS}" -arch "${ARCH}"
        Handle-Binary -Url $URL -Filename $madmaxFilename -BinaryName "chia_plot" -NewBinaryName "chia_plot_k34.exe"
    }
    else {
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
