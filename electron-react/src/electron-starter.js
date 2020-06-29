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
const ipcMain = require("electron").ipcMain;
const config = require("./config");
const dev_config = require("./dev_config");
const WebSocket = require("ws");
const daemon_rpc_ws = require("./util/config").daemon_rpc_ws;
const local_test = config.local_test;
var url = require("url");
const os = require("os");
const crypto = require("crypto");
const { request } = require("http");

global.sharedObj = { local_test: local_test };

/*************************************************************
 * py process
 *************************************************************/

const PY_MAC_DIST_FOLDER = "../../app.asar.unpacked/daemon";
const PY_WIN_DIST_FOLDER = "../../app.asar.unpacked/daemon";
const PY_DIST_FILE = "daemon";
const PY_FOLDER = "../src/daemon";
const PY_MODULE = "server"; // without .py suffix

let pyProc = null;
let ws = null;

const guessPackaged = () => {
  let packed;
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
  let processOptions = {};
  //processOptions.detached = true;
  //processOptions.stdio = "ignore";
  pyProc = null;
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
  //pyProc.unref();
};

const closeDaemon = callback => {
  let called_cb = false;
  try {
    const request_id = crypto.randomBytes(32).toString("hex");
    ws = new WebSocket(daemon_rpc_ws, {
      perMessageDeflate: false
    });
    ws.on("open", function open() {
      console.log("Opened websocket with", daemon_rpc_ws);
      const msg = {
        command: "exit",
        ack: false,
        origin: "wallet_ui",
        destination: "daemon",
        request_id
      };
      ws.send(JSON.stringify(msg));
    });
    ws.on("message", function incoming(message) {
      message = JSON.parse(message);
      if (message["ack"] === true && message["request_id"] === request_id) {
        called_cb = true;
        callback();
      }
    });
    ws.on("error", err => {
      if (err.errno === "ECONNREFUSED") {
        called_cb = true;
        callback();
      } else {
        console.log("Unexpected websocket error err ", err);
      }
    });
  } catch (e) {
    console.log("Error in websocket", e);
  }
  setTimeout(function() {
    if (!called_cb) {
      callback();
    }
  }, 15000);
};

const exitPyProc = e => {};

app.on("will-quit", exitPyProc);

/*************************************************************
 * window management
 *************************************************************/

let mainWindow = null;
let decidedToClose = false;

const createWindow = () => {
  decidedToClose = false;
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 1200,
    minWidth: 500,
    minHeight: 500,
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
  var closingUrl =
    process.env.ELECTRON_START_URL ||
    url.format({
      pathname: path.join(__dirname, "/../src/closing.html"),
      protocol: "file:",
      slashes: true
    });
  console.log(startUrl);

  mainWindow.loadURL(startUrl);

  mainWindow.once("ready-to-show", function() {
    mainWindow.show();
  });

  // Uncomment this to open devtools by default
  // if (!guessPackaged()) {
  //   mainWindow.webContents.openDevTools();
  // }
  mainWindow.on("close", e => {
    if (decidedToClose) {
      if (pyProc != null) {
        if (process.platform === "win32") {
          process.stdout.write("Killing daemon on windows");
          var cp = require("child_process");
          cp.execSync("taskkill /PID " + pyProc.pid + " /T /F");
        } else {
          process.stdout.write("Killing daemon on other platforms");
          pyProc.kill();
          pyProc = null;
          pyPort = null;
        }
      }
      return;
    }
    e.preventDefault();
    var choice = require("electron").dialog.showMessageBoxSync({
      type: "question",
      buttons: ["Yes", "No"],
      title: "Confirm",
      message:
        "Are you sure you want to quit? Plotting and farming will stop. Closing will take a few seconds."
    });
    if (choice == 1) {
      return;
    }
    mainWindow.loadURL(closingUrl);
    mainWindow.setBounds({ height: 500, width: 500 });

    decidedToClose = true;
    closeDaemon(() => {
      mainWindow.close();
    });
  });
};

const appReady = () => {
  closeDaemon(() => {
    createPyProc();
    ws.terminate();
    createWindow();
  });
};

app.on("ready", appReady);

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
