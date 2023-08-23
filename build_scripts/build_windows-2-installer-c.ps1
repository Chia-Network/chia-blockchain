Write-Output "   ---"
Write-Output "electron-builder B"
electron-builder build --win --x64 --config.productName="Chia"
Get-ChildItem dist\win-unpacked\resources
Write-Output "   ---"

If ($env:HAS_SIGNING_SECRET) {
   Write-Output "   ---"
   Write-Output "Sign App"
   signtool.exe sign /sha1 $env:SM_CODE_SIGNING_CERT_SHA1_HASH /tr http://timestamp.digicert.com /td SHA256 /fd SHA256 .\dist\ChiaSetup-$packageVersion.exe
   Write-Output "   ---"
   Write-Output "Verify signature"
   Write-Output "   ---"
   signtool.exe verify /v /pa .\dist\ChiaSetup-$packageVersion.exe
}   Else    {
   Write-Output "Skipping verify signatures - no authorization to install certificates"
}

Write-Output "   ---"
Write-Output "Moving final installers to expected location"
Write-Output "   ---"
Copy-Item ".\dist\win-unpacked" -Destination "$env:GITHUB_WORKSPACE\chia-blockchain-gui\Chia-win32-x64" -Recurse
mkdir "$env:GITHUB_WORKSPACE\chia-blockchain-gui\release-builds\windows-installer" -ea 0
Copy-Item ".\dist\ChiaSetup-$packageVersion.exe" -Destination "$env:GITHUB_WORKSPACE\chia-blockchain-gui\release-builds\windows-installer"

Write-Output "   ---"
Write-Output "Windows Installer complete"
Write-Output "   ---"
