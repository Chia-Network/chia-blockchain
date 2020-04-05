# Electron Wallet

## Install & Run

First install [Node LTS](https://nodejs.org/en/) and then

```bash
cd src
npm install --runtime=electron --target=1.7.6
npm audit fix
npm start
```

## Error

If run fails because of electron try doing this

```bash
npm install electron-rebuild && ./node_modules/.bin/electron-rebuild
```

## Building the installer

### You will need these tools

- [electron-packager](https://github.com/electron/electron-packager)
- [WiX Toolset](https://wixtoolset.org/) -
    which in turn needs [.NET 3.5](https://answers.microsoft.com/en-us/windows/forum/all/installingenabling-net-35-on-windows-10/fe7b4699-c096-4369-b06f-e1063da42e18)

Then run the `bundle-win32.ps1` PowerShell script.
