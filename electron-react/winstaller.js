const createWindowsInstaller = require('electron-winstaller').createWindowsInstaller
const path = require('path')

getInstallerConfig()
  .then(createWindowsInstaller)
  .catch((error) => {
    console.error(error.message || error)
    process.exit(1)
  })

function getInstallerConfig () {
  console.log('creating windows installer')
  const rootPath = path.join('./')
  const outPath = path.join(rootPath, 'release-builds')

  return Promise.resolve({
    appDirectory: path.join(rootPath, 'Chia-win32-x64/'),
    authors: 'Chia Networks',
    noMsi: true,
    outputDirectory: path.join(outPath, 'windows-installer'),
    exe: 'Chia.exe',
    setupExe: 'ChiaSetup.exe',
    setupIcon: path.join(rootPath, 'src', 'assets', 'img', 'chia.ico')
  })
}
