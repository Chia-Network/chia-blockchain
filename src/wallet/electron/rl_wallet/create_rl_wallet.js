const host = "ws://127.0.0.1:9256"
const jquery = require('jquery')
var QRCode = require('qrcode')
var canvas = document.getElementById('qr_canvas')
const Dialogs = require('dialogs')
const dialogs = Dialogs()
const WebSocket = require('ws');
var ws = new WebSocket(host);
let chia_formatter = require('../chia');

create_admin = document.querySelector('#create_admin');
create_user = document.querySelector('#create_user');
const electron = require('electron')
const app = electron.app
const BrowserWindow = electron.remote.BrowserWindow
const path = require('path')


create_admin.addEventListener('click', () => {
    create_admin_wallet()
});

create_user.addEventListener('click', () => {
    create_user_wallet()
});

function create_admin_wallet() {
    console.log("create admin rl wallet");
    data = {
        "wallet_type": "rl_wallet",
        "mode": "admin",
    }
    request = {
        "command": "create_new_wallet",
        "data": data
    }
    json_data = JSON.stringify(request);
    ws.send(json_data);
}

function create_user_wallet() {
    console.log("Create user rl wallet");
    data = {
        "wallet_type": "rl_wallet",
        "mode": "user",
    }
    request = {
        "command": "create_new_wallet",
        "data": data
    }
    json_data = JSON.stringify(request);
    ws.send(json_data);
}

function getQueryVariable(variable) {
    var query = global.location.search.substring(1);
    var vars = query.split('&');
    for (var i = 0; i < vars.length; i++) {
        var pair = vars[i].split('=');
        if (decodeURIComponent(pair[0]) == variable) {
            return decodeURIComponent(pair[1]);
        }
    }
    console.log('Query variable %s not found', variable);
}

var local_test = getQueryVariable("testing")
var g_wallet_id = getQueryVariable("wallet_id")

console.log("testing: " + local_test)
console.log("wallet_id: " + g_wallet_id)


function sleep(ms) {
    return new Promise((resolve) => {
        setTimeout(resolve, ms);
    });
}

function set_callbacks(socket) {
    /*
    Sets callbacks for socket events
    */

    socket.on('open', function open() {
        var msg = {"command": "start_server"}
        ws.send(JSON.stringify(msg));
    });

    socket.on('message', function incoming(incoming) {
        var message = JSON.parse(incoming);
        var command = message["command"];
        var data = message["data"];

        console.log("Received command: " + command);

        if (command == "create_new_wallet") {
            get_wallets();
        }
    });

    socket.on('error', function clear() {
        console.log("Not connected, reconnecting");
        connect(100);
    });
}

set_callbacks(ws);

async function connect(timeout) {
    /*
    Tries to connect to the host after a timeout
    */
    await sleep(timeout);
    ws = new WebSocket(host);
    set_callbacks(ws);
}


async function connection_checker() {
    await sleep(10000);
    await get_connection_info()
    connection_checker()
}


function get_wallets() {
    /*
    Sends websocket request to get list of all wallets available
    */
    /*data = {
        "command": "get_wallets",
    }
    json_data = JSON.stringify(data);
    ws.send(json_data);*/

    createWindow();

}

function createWindow(){
    //remote.getCurrentWindow().loadURL('../wallet-dark.html')

    newWindow = new BrowserWindow({
      width: 1500,
      height: 800,
      backgroundColor: '#131722',
      show: false,
      webPreferences: {
        nodeIntegration: true
    },})

    query = "?testing="+local_test + "&wallet_id=1"
    newWindow.loadURL(require('url').format({
    pathname: path.join(__dirname, "../wallet-dark.html"),
    protocol: 'file:',
    slashes: true
    }) + query
    )

    //newWindow.loadURL("../wallet-dark.html");

    newWindow.once('ready-to-show', function (){
        newWindow.show();
    });

    newWindow.on('closed', function() {
        newWindow = null;
    });
}



