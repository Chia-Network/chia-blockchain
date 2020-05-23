//handle setupevents as quickly as possible
const setupEvents = require("./setupEvents");
if (setupEvents.handleSquirrelEvent()) {
  // squirrel event handled and app will exit in 1000ms, so don't do anything else
  return;
}

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

const PY_MAC_DIST_FOLDER = "../daemon";
const PY_WIN_DIST_FOLDER = "../../app.asar.unpacked/daemon";
const PY_DIST_FILE = "daemon";
const PY_FOLDER = "../src/daemon";
const PY_MODULE = "server"; // without .py suffix

let pyProc = null;

const guessPackaged = () => {
  if (process.platform === "win32") {
    const fullPath = path.join(__dirname, PY_WIN_DIST_FOLDER);
    packed = require("fs").existsSync(fullPath);
    console.log(fullPath);
    console.log(packed);
    return packed;
  }
  const fullPath = path.join(__dirname, PY_MAC_DIST_FOLDER);
  packed = require("fs").existsSync(fullPath);
  console.log(fullPath);
  console.log(packed);
  return packed;
};

const getScriptPath = () => {
  if (!guessPackaged()) {
    return path.join(PY_FOLDER, PY_MODULE + ".py");
  }
  if (process.platform === "win32") {
    return path.join(__dirname, PY_WIN_DIST_FOLDER, PY_DIST_FILE + ".exe");
  }
  return path.join(__dirname, PY_MAC_DIST_FOLDER, PY_DIST_FILE);
};

const createPyProc = () => {
  let script = getScriptPath();
  processOptions = {};
  //processOptions.detached = true;
  //processOptions.stdio = "ignore";
  pyProc = null
  if (guessPackaged()) {
    try {
      console.log("Running python executable: ");
      const Process = require("child_process").spawn;
      pyProc = new Process(script, [], processOptions);
    } catch {
      console.log("Running python executable: Error: ");
      console.log("Script " + script);
    }
  } else {
    console.log("Running python script");
    console.log("Script " + script);

    const Process = require("child_process").spawn;
    pyProc = new Process("python", [script], processOptions);
  }
  if (pyProc != null) {
    pyProc.stdout.setEncoding("utf8");

    pyProc.stdout.on("data", function (data) {
      process.stdout.write(data.toString());
    });

    pyProc.stderr.setEncoding("utf8");
    pyProc.stderr.on("data", function (data) {
      //Here is where the error output goes
      process.stdout.write("stderr: " + data.toString());
    });

    pyProc.on("close", function (code) {
      //Here you can get the exit code of the script
      console.log("closing code: " + code);
    });

    console.log("child process success");
  }
  //pyProc.unref();
};

const exitPyProc = () => {
  // Should be a setting
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
    minWidth: 600,
    minHeight: 800,
    backgroundColor: "#ffffff",
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

  if (dev_config.react_tool) {
    BrowserWindow.addDevToolsExtension(
      path.join(os.homedir(), dev_config.react_tool)
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

  if (!guessPackaged()) {
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
