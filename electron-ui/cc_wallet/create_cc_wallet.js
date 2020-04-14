const host = "ws://127.0.0.1:9256"
var QRCode = require('qrcode')
var canvas = document.getElementById('qr_canvas')
const Dialogs = require('dialogs')
const dialogs = Dialogs()
const WebSocket = require('ws');
var ws = new WebSocket(host);
const { get_query_variable } = require("../utils");
let chia_formatter = require('../chia');

let generate_color = document.querySelector('#generate_color');
let input_color = document.querySelector('#input_color');
let input_color_text = document.querySelector('#input_color_text')
const electron = require('electron')
const app = electron.app
const BrowserWindow = electron.remote.BrowserWindow
const path = require('path')

var global_input_color_continue = false


generate_color.addEventListener('click', () => {
    create_wallet_generate_color()
});

input_color.addEventListener('click', () => {
    create_wallet_input_color()
});


function create_wallet_generate_color() {
    console.log("create cc wallet by generating a new color");
    data = {
        "wallet_type": "cc_wallet",
        "mode": "generate_color",
    }
    request = {
        "command": "create_new_wallet",
        "data": data
    }
    json_data = JSON.stringify(request);
    ws.send(json_data);
}

function create_wallet_input_color() {
    console.log("create cc wallet by inputing an existing color");

    try {
        color = input_color_text.value;
        if (color.startsWith("0x") || color.startsWith("0X")) {
            color = color.substring(2);
        }

        /*
        needs the correct length below and correct the wording
        if (color.length != 64) {
            alert("Please enter a 32 byte color in hexadecimal format");
            return;
        }
        */

        global_input_color_continue = true;

        data = {
          "wallet_type": "cc_wallet",
          "mode": "input_color",
          "color": color,
        }

        request = {
            "command": "create_new_wallet",
            "data": data
        }

        json_data = JSON.stringify(request);
        ws.send(json_data);
    } catch (error) {
        alert("Error creating new wallet using an existing color").
        global_input_color_continue = false;
    }
    if (global_input_color_continue) {
      document.location = "../wallet-dark.html?wallet_id=1";
    }
  }

var local_test = get_query_variable("testing")
var g_wallet_id = get_query_variable("wallet_id")

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
            go_to_main_wallet();
        }
    });

    socket.on('error', function clear() {
        console.log("CC wallet not connected, reconnecting");
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

function go_to_main_wallet(){
    //remote.getCurrentWindow().loadURL('../wallet-dark.html')

    newWindow = electron.remote.getCurrentWindow()

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
