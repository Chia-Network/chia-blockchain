const createWindowsInstaller = require('electron-winstaller').createWindowsInstaller
const path = require('path')

getInstallerConfig()
  .then(createWindowsInstaller)
  .catch((error) => {
    console.error(error.message || error)
    process.exit(1)
  })

function getInstallerConfig () {
  console.log('Creating windows installer')
  const rootPath = path.join('./')
  const outPath = path.join(rootPath, 'release-builds')

  return Promise.resolve({
    appDirectory: path.join(rootPath, 'Chia-win32-x64'),
    authors: 'Chia Network',
    version: process.env.CHIA_INSTALLER_VERSION,
    noMsi: true,
    outputDirectory: path.join(outPath, 'windows-installer'),
    exe: 'Chia.exe',
    setupExe: 'ChiaSetup-' + process.env.CHIA_INSTALLER_VERSION + '.exe',
    setupIcon: path.join(rootPath, 'src', 'assets', 'img', 'chia.ico')
  })
}
