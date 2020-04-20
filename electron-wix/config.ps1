# shared variables
$env:walletProductName = "chia-wallet"
$env:blockchainProductName = "chia-blockchain"
# $env:version = "0.1.5" # all packages share the same version
$env:resourceDir = ".\resources" # bitmaps, icons etc
$env:prereqDir = ".\prerequisites" # location for any pre-req installers

$buildDir = ".\build" # where temp and final build output go
$finalDir = ".\final" # where temp and final build output go
$sourceDir = ".\src" # the location of wxs files etc
$electronPackagerDir = $env:walletProductName + "-win32-x64" # the folder that electron-packager creates

# tool locations
$signtoolPath = "${env:ProgramFiles(x86)}\Windows Kits\10\bin\10.0.18362.0\x64"
$wixPath = "${env:ProgramFiles(x86)}\WiX Toolset v3.11\bin"

$env:path += ";$signtoolPath;$wixPath" # add to path

function Sign-Item {
    Param ($packageName)

    $timeURL = "http://timestamp.comodoca.com/authenticode"
    $pfxPath = "$env:HOMEDRIVE\$env:HOMEPATH\selfsigncert.pfx"
    $CERT_PASSWORD = "my_password"

    # if a signing cert is specified, sign the package
    if (Test-Path $pfxPath -PathType leaf) {
        Write-Host "Signing $packageName"
        signtool sign /f $pfxPath /p $CERT_PASSWORD /t $timeURL /v "$packageName"
        if ($LastExitCode) { exit $LastExitCode }
    }
}
