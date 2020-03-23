const electron = require('electron')
const app = electron.app
const BrowserWindow = electron.BrowserWindow
const path = require('path')
const WebSocket = require('ws');
const local_test = true

var ui_html = "wallet-dark.html"

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
    //pyProc = require('child_process').spawn('python', [script, "--testing", local_test])
  }

    if (pyProc != null) {
        pyProc.stdout.setEncoding('utf8');

        pyProc.stdout.on('data', function(data) {
            console.log(data.toString());
        });

        pyProc.stderr.setEncoding('utf8');
        pyProc.stderr.on('data', function(data) {
            //Here is where the error output goes
            console.log('stderr: ' + data.toString());
        });

        pyProc.on('close', function(code) {
            //Here you can get the exit code of the script
            console.log('closing code: ' + code);
        });

        console.log('child process success')
    }
}

const exitPyProc = () => {
  if (pyProc != null) {
    pyProc.kill()
    pyProc = null
    pyPort = null
  }
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
      backgroundColor: '#131722',
      show: false,
      webPreferences: {
        nodeIntegration: true
    },})

  query = "?testing="+local_test + "&wallet_id=1"
  mainWindow.loadURL(require('url').format({
    pathname: path.join(__dirname, ui_html),
    protocol: 'file:',
    slashes: true
  }) + query
  )

  mainWindow.once('ready-to-show', function (){
        mainWindow.show();
  });

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
