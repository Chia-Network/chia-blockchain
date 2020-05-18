const electron = require("electron");
const app = electron.app;
const BrowserWindow = electron.BrowserWindow;
const path = require("path");
const WebSocket = require("ws");
const ipcMain = require("electron").ipcMain;
const config = require("./config");
const dev_config = require("./dev_config");
const local_test = config.local_test;
const redux_tool = dev_config.redux_tool;
var url = require("url");
const Tail = require("tail").Tail;
const os = require("os");

// Only takes effect if local_test is false. Connects to a local introducer.
var local_introducer = false;

global.sharedObj = { local_test: local_test };

/*************************************************************
 * py process
 *************************************************************/

const PY_DIST_FOLDER = "pydist";
const PY_FOLDER = "../src/daemon";
const PY_MODULE = "server"; // without .py suffix

let pyProc = null;
let pyPort = null;

const guessPackaged = () => {
  const fullPath = path.join(__dirname, PY_DIST_FOLDER);
  return require("fs").existsSync(fullPath);
};

const getScriptPath = () => {
  if (!guessPackaged()) {
    return path.join(PY_FOLDER, PY_MODULE + ".py");
  }
  if (process.platform === "win32") {
    return path.join(PY_DIST_FOLDER, PY_MODULE, PY_MODULE + ".exe");
  }
  return path.join(PY_DIST_FOLDER, PY_MODULE, PY_MODULE);
};

const selectPort = () => {
  pyPort = 9256;
  return pyPort;
};

const createPyProc = () => {
  let script = getScriptPath();
  if (!local_test && local_introducer) {
    additional_args = [
      "--testing",
      local_test,
      "--introducer_peer.host",
      "127.0.0.1",
      "--introducer_peer.port",
      "8445"
    ];
  } else {
    additional_args = ["--testing", local_test];
  }
  if (guessPackaged()) {
    pyProc = require("child_process").execFile(script, additional_args);
  } else {
    pyProc = require("child_process").spawn(
      "python",
      [script].concat(additional_args)
    );
  }
  if (pyProc != null) {
    pyProc.stdout.setEncoding("utf8");

    pyProc.stdout.on("data", function(data) {
      process.stdout.write(data.toString());
    });

    pyProc.stderr.setEncoding("utf8");
    pyProc.stderr.on("data", function(data) {
      //Here is where the error output goes
      process.stdout.write("stderr: " + data.toString());
    });

    pyProc.on("close", function(code) {
      //Here you can get the exit code of the script
      console.log("closing code: " + code);
    });

    console.log("child process success");
  }
};

const exitPyProc = () => {
  if (pyProc != null) {
    pyProc.kill();
    pyProc = null;
    pyPort = null;
  }
};

app.on("ready", createPyProc);
app.on("will-quit", exitPyProc);

/*************************************************************
 * window management
 *************************************************************/

let mainWindow = null;

const createWindow = () => {
  mainWindow = new BrowserWindow({
    width: 1500,
    height: 800,
    backgroundColor: "#131722",
    show: false,
    webPreferences: {
      preload: __dirname + "/preload.js",
      nodeIntegration: true
    }
  });

  if (dev_config.redux_tool) {
    BrowserWindow.addDevToolsExtension(
      path.join(os.homedir(), dev_config.redux_tool)
    );
  }

  var startUrl =
    process.env.ELECTRON_START_URL ||
    url.format({
      pathname: path.join(__dirname, "/../build/index.html"),
      protocol: "file:",
      slashes: true
    });
  console.log(startUrl);

  mainWindow.loadURL(startUrl);

  mainWindow.once("ready-to-show", function() {
    mainWindow.show();
  });

  if (!local_test) {
    mainWindow.webContents.openDevTools();
  }

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
};

app.on("ready", createWindow);

app.on("window-all-closed", () => {
  app.quit();
});

app.on("activate", () => {
  if (mainWindow === null) {
    createWindow();
  }
});

ipcMain.on("load-page", (event, arg) => {
  mainWindow.loadURL(
    require("url").format({
      pathname: path.join(__dirname, arg.file),
      protocol: "file:",
      slashes: true
    }) + arg.query
  );
});
