## Bundling the installer

Install .NET 3.5.1 (Server Manager)
Install WiX (https://wixtoolset.org/)

In PowerShell

cd electron-ui
npm install --runtime=electron --target=1.7.6

verify runs with npm start

cd ../electron-wix
npm install electron-packager -g

edit version number in bundle-win32.ps1

.\bundle-win32.ps1

MSI will be in electron-wix folder
