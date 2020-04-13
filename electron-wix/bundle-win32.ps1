# add wix to path
$env:Path += ";${env:ProgramFiles(x86)}\WiX Toolset v3.11\bin"
$env:exename = "chia-wallet" # if you update this make sure to update .gitignore
$env:version = "0.1.4"
$electronpackagerdir = $env:exename + "-win32-x64"
$buildDir = ".\build"

function MakeMsi($scope, $installRoot)
{
    $env:installScope = $scope
    $env:installRoot =  $installRoot
    $tempName = "electron-packager-files-$scope"
    $msiName = "$env:exename-$env:version.msi"

    Write-Host "Making $scope installer installed to $installRoot"

    # this generates package-files.wxs from the contents of the electron packager folder
    if ($scope -eq "perMachine") {
        $msiName = "$env:exename-$env:version-$scope.msi" # append perMachine for this non-default installer
        heat dir $electronpackagerdir -cg ChiaFiles -gg -scom -sreg -sfrag -srd -dr INSTALLDIR -out "$buildDir\$tempName.wxs"
    }
    else {
        # for perUser install the output of heat needs post processing (see the xslt for details)
        heat dir $electronpackagerdir -cg ChiaFiles -gg -scom -sreg -sfrag -srd -dr INSTALLDIR -out "$buildDir\$tempName.wxs" -t "$scope.xslt"
    }
    if ($LastExitCode) { exit $LastExitCode }

    # compile the installer
    candle "$buildDir\$tempName.wxs" chia.wxs -o "$buildDir\"
    if ($LastExitCode) { exit $LastExitCode }

    # link the installer
    light -ext WixUIExtension "$buildDir\$tempName.wixobj" "$buildDir\chia.wixobj" -b $electronpackagerdir -o "$buildDir\$msiName" -sw1076
    if ($LastExitCode) { exit $LastExitCode }

    Write-Host "Successfully built $msiName"
}

# remove any exisitng outputs
Write-Host "Cleaning any previous outputs"
Remove-Item $electronpackagerdir -Recurse -Force -ErrorAction Ignore
Remove-Item "$buildDir" -Recurse -Force -ErrorAction Ignore
New-Item -ItemType Directory -Path "$buildDir"

# package up the electron stuff and sources
electron-packager ../electron-ui $env:exename --platform=win32
if ($LastExitCode) { exit $LastExitCode }

MakeMsi "perUser" "LocalAppDataFolder"

# uncomment this line to make a perMachine installer
# MakeMsi "perMachine" "ProgramFilesFolder"
