const electron = require('electron')
const app = electron.app
const BrowserWindow = electron.BrowserWindow
const path = require('path')
const WebSocket = require('ws');
const local_test = false

var ui_html = "wallet-dark.html"
if (local_test) {
    // Has farm block button
    ui_html = "wallet-dark-test.html"
}

/*************************************************************
 * py process
 *************************************************************/

const PY_DIST_FOLDER = 'pydist'
const PY_FOLDER = 'rpc'
const PY_MODULE = 'websocket_server' // without .py suffix

let pyProc = null
let pyPort = null

const guessPackaged = () => {
  const fullPath = path.join(__dirname, PY_DIST_FOLDER)
  return require('fs').existsSync(fullPath)
}

const getScriptPath = () => {
  if (!guessPackaged()) {
    return path.join( PY_FOLDER, PY_MODULE + '.py')
  }
  if (process.platform === 'win32') {
    return path.join(PY_DIST_FOLDER, PY_MODULE, PY_MODULE + '.exe')
  }
  return path.join(PY_DIST_FOLDER, PY_MODULE, PY_MODULE)
}

const selectPort = () => {
  pyPort = 9256
  return pyPort
}

const createPyProc = () => {
  let script = getScriptPath()

  if (guessPackaged()) {
    pyProc = require('child_process').execFile(script, ["--testing", local_test])
  } else {
    pyProc = require('child_process').spawn('python', [script, "--testing", local_test])
  }

  if (pyProc != null) {
    console.log('child process success')
  }
}

const exitPyProc = () => {
  pyProc.kill()
  pyProc = null
  pyPort = null
}

app.on('ready', createPyProc)
app.on('will-quit', exitPyProc)


/*************************************************************
 * window management
 *************************************************************/

let mainWindow = null

const createWindow = () => {
  console.log(process.versions)
  mainWindow = new BrowserWindow({
      width: 1500,
      height: 800,
      webPreferences: {
        nodeIntegration: true
    },})

  mainWindow.loadURL(require('url').format({
    pathname: path.join(__dirname, ui_html),
    protocol: 'file:',
    slashes: true
  }))
  mainWindow.webContents.openDevTools()

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

app.on('ready', createWindow)

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('activate', () => {
  if (mainWindow === null) {
    createWindow()
  }
})
