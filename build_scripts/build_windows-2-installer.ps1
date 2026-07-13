# $env:path should contain a path to editbin.exe and signtool.exe

$ErrorActionPreference = "Stop"

mkdir build_scripts\win_build

git status
git submodule

if (-not (Test-Path env:CHIA_INSTALLER_VERSION)) {
  $env:CHIA_INSTALLER_VERSION = '0.0.0'
  Write-Output "WARNING: No environment variable CHIA_INSTALLER_VERSION set. Using 0.0.0"
}
if (-not (Test-Path env:CHIA_SEMVER_VERSION)) {
  $env:CHIA_SEMVER_VERSION = $env:CHIA_INSTALLER_VERSION
  Write-Output "WARNING: No environment variable CHIA_SEMVER_VERSION set. Using $env:CHIA_INSTALLER_VERSION"
}

Write-Output "Chia Version is: $env:CHIA_INSTALLER_VERSION"
Write-Output "Chia Semver Version is: $env:CHIA_SEMVER_VERSION"
Write-Output "   ---"

Write-Output "   ---"
Write-Output "Use pyinstaller to create chia .exe's"
Write-Output "   ---"
$SPEC_FILE = (py -c 'import sys; from pathlib import Path; path = Path(sys.argv[1]); print(path.absolute().as_posix())' "pyinstaller.spec")
pyinstaller --log-level INFO $SPEC_FILE

Write-Output "   ---"
Write-Output "Creating a directory of licenses from pip and npm packages"
Write-Output "   ---"
bash ./build_win_license_dir.sh

Write-Output "   ---"
Write-Output "Copy chia executables to chia-blockchain-gui\"
Write-Output "   ---"
Copy-Item "dist\daemon" -Destination "..\chia-blockchain-gui\packages\gui\" -Recurse

Write-Output "   ---"
Write-Output "Setup npm packager"
Write-Output "   ---"
Set-Location -Path ".\npm_windows" -PassThru
npm ci
$NPM_PATH = $pwd.PATH + "\node_modules\.bin"

Set-Location -Path "..\..\" -PassThru

Write-Output "   ---"
Write-Output "Prepare Electron packager"
Write-Output "   ---"
$Env:NODE_OPTIONS = "--max-old-space-size=3000"

# Change to the GUI directory
Set-Location -Path "chia-blockchain-gui\packages\gui" -PassThru

Write-Output "   ---"
Write-Output "Increase the stack for chia command for (chia plots create) chiapos limitations"
# editbin.exe needs to be in the path
editbin.exe /STACK:8000000 daemon\chia.exe
Write-Output "   ---"

$packageVersion = "$env:CHIA_INSTALLER_VERSION"
$packageName = "Chia-$packageVersion"

Write-Output "packageName is $packageName"

Write-Output "   ---"
Write-Output "npm version in package.json"
choco install jq
cp package.json package.json.orig
jq --arg VER "$env:CHIA_SEMVER_VERSION" '.version=$VER' package.json > temp.json
rm package.json
mv temp.json package.json
Write-Output "   ---"

# Signing is done with signtool /dlib after packaging. electron-builder signing is
# disabled via win.signtoolOptions.sign=null in electron-builder.json.
$env:CSC_IDENTITY_AUTO_DISCOVERY = "false"

function Request-AzureFederatedToken {
    # prod credential chain needs AZURE_FEDERATED_TOKEN_FILE (not Azure CLI).
    # Request a fresh GitHub OIDC token immediately before signing so it does not expire
    # during the long pyinstaller / electron-builder packaging steps above.
    if (-not $env:ACTIONS_ID_TOKEN_REQUEST_URL -or -not $env:ACTIONS_ID_TOKEN_REQUEST_TOKEN) {
        throw "ACTIONS_ID_TOKEN_REQUEST_URL/TOKEN not available; ensure permissions.id-token: write is set"
    }
    if (-not $env:AZURE_TENANT_ID -or -not $env:AZURE_CLIENT_ID) {
        throw "AZURE_TENANT_ID and AZURE_CLIENT_ID must be set for AZURE_TOKEN_CREDENTIALS=prod"
    }

    $tokenUrl = "$($env:ACTIONS_ID_TOKEN_REQUEST_URL)&audience=api://AzureADTokenExchange"
    $headers = @{ Authorization = "Bearer $($env:ACTIONS_ID_TOKEN_REQUEST_TOKEN)" }
    $response = Invoke-RestMethod -Uri $tokenUrl -Headers $headers -Method GET
    if (-not $response.value) {
        throw "Failed to obtain GitHub OIDC token for Azure federated credential"
    }

    $tokenFile = Join-Path $env:RUNNER_TEMP "azure-federated-token"
    Set-Content -Path $tokenFile -Value $response.value -NoNewline
    $env:AZURE_FEDERATED_TOKEN_FILE = $tokenFile
    Write-Output "Wrote Azure federated token to $tokenFile"
}

function Sign-WithAzureArtifactSigning {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath
    )

    if (-not $env:AZURE_CODE_SIGNING_DLIB -or -not (Test-Path $env:AZURE_CODE_SIGNING_DLIB)) {
        throw "AZURE_CODE_SIGNING_DLIB is not set or does not exist: $env:AZURE_CODE_SIGNING_DLIB"
    }
    if (-not $env:AZURE_CODE_SIGNING_METADATA -or -not (Test-Path $env:AZURE_CODE_SIGNING_METADATA)) {
        throw "AZURE_CODE_SIGNING_METADATA is not set or does not exist: $env:AZURE_CODE_SIGNING_METADATA"
    }

    Write-Output "Signing $FilePath"
    signtool.exe sign /v /fd SHA256 /tr "http://timestamp.acs.microsoft.com" /td SHA256 `
        /dlib $env:AZURE_CODE_SIGNING_DLIB `
        /dmdf $env:AZURE_CODE_SIGNING_METADATA `
        $FilePath
    if ($LASTEXITCODE -ne 0) {
        throw "Azure Artifact Signing failed for $FilePath with exit code $LASTEXITCODE"
    }
}

Write-Output "   ---"
Write-Output "electron-builder create package directory"
Write-Output "   ---"
& "$NPM_PATH/electron-builder.ps1" --version
& "$NPM_PATH/electron-builder.ps1" build --win --x64 --config.productName="Chia" --dir --config ../../../build_scripts/electron-builder.json
if ($LASTEXITCODE -ne 0) {
    throw "electron-builder package-directory build failed with exit code $LASTEXITCODE"
}
Get-ChildItem dist\win-unpacked\resources
Write-Output "   ---"

If ($env:HAS_SIGNING_SECRET) {
    Write-Output "   ---"
    Write-Output "Sign all EXEs with Azure Artifact Signing"
    Write-Output "   ---"
    Request-AzureFederatedToken
    Get-ChildItem ".\dist\win-unpacked" -Recurse -File |
        Where-Object { $_.Extension -eq ".exe" } |
        ForEach-Object {
            Sign-WithAzureArtifactSigning -FilePath $_.FullName
            Write-Output "Verify signature"
            signtool.exe verify /v /pa $_.FullName
            if ($LASTEXITCODE -ne 0) {
                throw "Signature verification failed for $($_.FullName)"
            }
        }
} Else {
    Write-Output "Skipping signing/verify - no authorization for Azure Artifact Signing"
}

Write-Output "   ---"
Write-Output "electron-builder create installer"
Write-Output "   ---"
& "$NPM_PATH/electron-builder.ps1" build --win --x64 --config.productName="Chia" --pd ".\dist\win-unpacked" --config ../../../build_scripts/electron-builder.json --publish never
if ($LASTEXITCODE -ne 0) {
    throw "electron-builder installer build failed with exit code $LASTEXITCODE"
}
Write-Output "   ---"

$installerPath = ".\dist\ChiaSetup-$packageVersion.exe"

If ($env:HAS_SIGNING_SECRET) {
    Write-Output "   ---"
    Write-Output "Sign Final Installer App"
    Write-Output "   ---"
    Request-AzureFederatedToken
    Sign-WithAzureArtifactSigning -FilePath $installerPath

    Write-Output "   ---"
    Write-Output "Verify final installer signature"
    Write-Output "   ---"
    signtool.exe verify /v /pa $installerPath
    if ($LASTEXITCODE -ne 0) {
        throw "Signature verification failed for $installerPath"
    }

    $signature = Get-AuthenticodeSignature $installerPath
    $signature | Select-Object Status, StatusMessage
    $signature.SignerCertificate | Select-Object Subject, Issuer, Thumbprint, NotBefore, NotAfter
} Else {
    Write-Output "Skipping signing/verify - no authorization for Azure Artifact Signing"
}

Write-Output "   ---"
Write-Output "Moving final installers to expected location"
Write-Output "   ---"
Copy-Item ".\dist\win-unpacked" -Destination "$env:GITHUB_WORKSPACE\chia-blockchain-gui\Chia-win32-x64" -Recurse
mkdir "$env:GITHUB_WORKSPACE\chia-blockchain-gui\release-builds\windows-installer" -ea 0
Copy-Item $installerPath -Destination "$env:GITHUB_WORKSPACE\chia-blockchain-gui\release-builds\windows-installer"

Write-Output "   ---"
Write-Output "Windows Installer complete"
Write-Output "   ---"
