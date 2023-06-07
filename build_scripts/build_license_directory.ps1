# PULL IN LICENSES USING NPM - LICENSE CHECKER
npm install -g license-checker

Set-Location "..\chia-blockchain-gui"

npm ci

$sum = license-checker --summary
Write-Output $sum

$license_list = license-checker --json | ConvertFrom-Json | ForEach-Object { $_.licenseFile } | Where-Object { $_ -ne $null }

# Split the license list by newline character into an array
$licenses_array = $license_list -split "`n"

# Print the contents of the array
$licenses_array

foreach ($i in $licenses_array) {
    $dirname = "licenses\$([System.IO.Path]::GetDirectoryName($i) | Split-Path -Leaf)"
    New-Item -ItemType Directory -Force -Path $dirname | Out-Null
    Write-Output $dirname
    Copy-Item $i -Destination $dirname
}

Move-Item licenses\ ..\build_scripts\dist\daemon

Set-Location "..\build_scripts"

# PULL IN THE LICENSES FROM PIP-LICENSES
pip install pip-licenses

# Capture the output of the command in a variable
$output = pip-licenses -l -f json | ConvertFrom-Json | ForEach-Object { $_.LicenseFile } | Where-Object { $_ -ne "UNKNOWN" }

# Initialize an empty array
$license_path_array = @()

# Read the output line by line into the array
foreach ($line in $output) {
    $license_path_array += $line
}

# Create a directory for each license and copy the license file over
foreach ($i in $license_path_array) {
    $dirname = "dist\daemon\licenses\$([System.IO.Path]::GetDirectoryName($i) | Split-Path -Leaf)"
    Write-Output $dirname
    New-Item -ItemType Directory -Force -Path $dirname | Out-Null
    Copy-Item $i -Destination $dirname
    Write-Output $i
}

Get-ChildItem dist\daemon -Force
