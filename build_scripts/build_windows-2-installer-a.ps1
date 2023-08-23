# $env:path should contain a path to editbin.exe and signtool.exe

$ErrorActionPreference = "Stop"

mkdir build_scripts\win_build

git status
git submodule

if (-not (Test-Path env:CHIA_INSTALLER_VERSION)) {
  $env:CHIA_INSTALLER_VERSION = '0.0.0'
  Write-Output "WARNING: No environment variable CHIA_INSTALLER_VERSION set. Using 0.0.0"
}
Write-Output "Chia Version is: $env:CHIA_INSTALLER_VERSION"
Write-Output "   ---"

Write-Output "   ---"
Write-Output "Use pyinstaller to create chia .exe's"
Write-Output "   ---"
$SPEC_FILE = (python -c 'import chia; print(chia.PYINSTALLER_SPEC_PATH)') -join "`n"
pyinstaller --log-level INFO $SPEC_FILE

Write-Output "   ---"
Write-Output "Creating a directory of licenses from pip and npm packages"
Write-Output "   ---"
bash ./build_win_license_dir.sh

Write-Output "   ---"
Write-Output "Copy chia executables to chia-blockchain-gui\"
Write-Output "   ---"
Copy-Item "dist\daemon" -Destination "..\chia-blockchain-gui\packages\gui\" -Recurse

signtool.exe sign /sha1 $env:SM_CODE_SIGNING_CERT_SHA1_HASH /tr http://timestamp.digicert.com /td SHA256 /fd SHA256 ..\chia-blockchain-gui\packages\gui\chia.exe
signtool.exe sign /sha1 $env:SM_CODE_SIGNING_CERT_SHA1_HASH /tr http://timestamp.digicert.com /td SHA256 /fd SHA256 ..\chia-blockchain-gui\packages\gui\daemon.exe
signtool.exe sign /sha1 $env:SM_CODE_SIGNING_CERT_SHA1_HASH /tr http://timestamp.digicert.com /td SHA256 /fd SHA256 ..\chia-blockchain-gui\packages\gui\start_crawler.exe
signtool.exe sign /sha1 $env:SM_CODE_SIGNING_CERT_SHA1_HASH /tr http://timestamp.digicert.com /td SHA256 /fd SHA256 ..\chia-blockchain-gui\packages\gui\start_data_layer.exe
signtool.exe sign /sha1 $env:SM_CODE_SIGNING_CERT_SHA1_HASH /tr http://timestamp.digicert.com /td SHA256 /fd SHA256 ..\chia-blockchain-gui\packages\gui\start_data_layer_http.exe
signtool.exe sign /sha1 $env:SM_CODE_SIGNING_CERT_SHA1_HASH /tr http://timestamp.digicert.com /td SHA256 /fd SHA256 ..\chia-blockchain-gui\packages\gui\start_data_layer_s3_plugin.exe
signtool.exe sign /sha1 $env:SM_CODE_SIGNING_CERT_SHA1_HASH /tr http://timestamp.digicert.com /td SHA256 /fd SHA256 ..\chia-blockchain-gui\packages\gui\start_farmer.exe
signtool.exe sign /sha1 $env:SM_CODE_SIGNING_CERT_SHA1_HASH /tr http://timestamp.digicert.com /td SHA256 /fd SHA256 ..\chia-blockchain-gui\packages\gui\start_full_node.exe
signtool.exe sign /sha1 $env:SM_CODE_SIGNING_CERT_SHA1_HASH /tr http://timestamp.digicert.com /td SHA256 /fd SHA256 ..\chia-blockchain-gui\packages\gui\start_harvester.exe
signtool.exe sign /sha1 $env:SM_CODE_SIGNING_CERT_SHA1_HASH /tr http://timestamp.digicert.com /td SHA256 /fd SHA256 ..\chia-blockchain-gui\packages\gui\start_introducer.exe
signtool.exe sign /sha1 $env:SM_CODE_SIGNING_CERT_SHA1_HASH /tr http://timestamp.digicert.com /td SHA256 /fd SHA256 ..\chia-blockchain-gui\packages\gui\start_seeder.exe
signtool.exe sign /sha1 $env:SM_CODE_SIGNING_CERT_SHA1_HASH /tr http://timestamp.digicert.com /td SHA256 /fd SHA256 ..\chia-blockchain-gui\packages\gui\start_timelord.exe
signtool.exe sign /sha1 $env:SM_CODE_SIGNING_CERT_SHA1_HASH /tr http://timestamp.digicert.com /td SHA256 /fd SHA256 ..\chia-blockchain-gui\packages\gui\start_wallet.exe
signtool.exe sign /sha1 $env:SM_CODE_SIGNING_CERT_SHA1_HASH /tr http://timestamp.digicert.com /td SHA256 /fd SHA256 ..\chia-blockchain-gui\packages\gui\timelord_launcher.exe

