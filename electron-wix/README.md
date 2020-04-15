# Building the installer

## Tooling

- [Install electron-packager](https://github.com/electron/electron-packager) in CLI mode `npm install electron-packager -g`
- [Install .NET 3.5.1](https://docs.microsoft.com/en-us/dotnet/framework/install/dotnet-35-windows-10) (Server Manager)
- [Install WiX](https://wixtoolset.org/)

## Electron

In PowerShell make sure that electron and all dependencies are present:

````PowerShell
# from the electron-ui folder
npm install --runtime=electron --target=1.7.6
````

Verify that the wallet runs with `npm start`.

## Build script

Edit the version number in `bundle-win32.ps1`.

````PowerShell
# from the electron-wix folder
.\bundle-win32.ps1
````

MSI will be in the `electron-wix\build` folder.

## Machine-wide installation

By default the installer is per user. In order to install per machine, run the following from an elevated command prompt:

````PowerShell
# replace the msi name with the current version
msiexec /i chia-wallet-0.1.4.msi MSIINSTALLPERUSER="" ALLUSERS=1
````
