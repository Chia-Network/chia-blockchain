const { wallet_rpc_host_and_port } = require("../config");
const Dialogs = require('dialogs')
const dialogs = Dialogs()
const WebSocket = require('ws');
let chia_formatter = require('../chia');
const electron = require('electron')
const { get_query_variable } = require("../utils");
const path = require('path')

// HTML
let generate_colour = document.querySelector('#generate_colour');
let amount = document.querySelector('#generate_colour_text');
let input_colour = document.querySelector('#input_colour');
let colour = document.querySelector('#input_colour_text')
let balance_textfield = document.querySelector('#balance_textfield')

// Global variables
var global_balance = 0.0
var global_creating_wallet = false
var local_test = electron.remote.getGlobal('sharedObj').local_test;
var g_wallet_id = get_query_variable("wallet_id")
var ws = new WebSocket(wallet_rpc_host_and_port);


generate_colour.addEventListener('click', () => {
    create_wallet_generate_colour()
});

input_colour.addEventListener('click', () => {
    create_wallet_input_colour()
});


function create_wallet_generate_colour() {

    if (global_creating_wallet) {
        return;
    }

    try {
      amount_value = parseFloat(Number(amount.value));
      mojo_value = chia_formatter(amount_value, 'chia').to('mojo').value()
      if (isNaN(mojo_value)) {
          dialogs.alert("Please enter a valid numeric amount");
          return;
      }
      if (amount_value > global_balance) {
        dialogs.alert("Amount may not be greater than your available balance");
        return;
      }

      global_creating_wallet = true;
      generate_colour.disabled = true;
      generate_colour.innerHTML = "CREATING...";

      data = {
          "wallet_type": "cc_wallet",
          "mode": "new",
          "amount": mojo_value,
      }
      request = {
          "command": "create_new_wallet",
          "data": data
      }
      json_data = JSON.stringify(request);
      ws.send(json_data);
    } catch (error) {
        dialogs.alert("Error generating a new colour").
        global_creating_wallet = false;
    }
}

function create_wallet_response(response) {
    /*
    Called when response is received for create_wallet_generate_colour request
    */
   status = response["success"];
   if (status === "true") {
       go_to_main_wallet();
   } else if (status === "false") {
       dialogs.alert("Error creating coloured coin wallet.", ok => {});
       global_creating_wallet = false;
   }
}

function create_wallet_input_colour() {
    if (global_creating_wallet) {
        return;
    }

    try {
        colour = input_colour_text.value;
        if (colour.startsWith("0x") || colour.startsWith("0X")) {
            colour = colour.substring(2);
        }

        regexp = /^[0-9a-fA-F]+$/;
        if (!regexp.test(colour))
          {
            alert("Please enter a 32 byte colour in hexadecimal format");
            return;
          }

        if (colour.length != 64) {
            alert("Please enter a 32 byte colour in hexadecimal format");
            return;
        }

        global_creating_wallet = true;
        input_colour.disabled = true;
        input_colour.innerHTML = "CREATING...";

        data = {
          "wallet_type": "cc_wallet",
          "mode": "existing",
          "colour": colour,
        }

        request = {
            "command": "create_new_wallet",
            "data": data
        }

        json_data = JSON.stringify(request);
        ws.send(json_data);
    } catch (error) {
        dialogs.alert("Error creating new wallet using an existing colour").
        global_creating_wallet = false;
    }
}

async function get_wallet_balance(id) {
    /*
    Sends websocket request to get wallet balance
    */
    data = {
        "wallet_id": id,
    }

    request = {
        "command": "get_wallet_balance",
        "data": data
    }

    json_data = JSON.stringify(request);
    ws.send(json_data);
}

function get_wallet_balance_response(response) {
    if (response["success"]) {
        var confirmed = parseInt(response["confirmed_wallet_balance"])
        var unconfirmed = parseInt(response["unconfirmed_wallet_balance"])
        var pending = confirmed - unconfirmed
        var wallet_id = response["wallet_id"]

        chia_confirmed = chia_formatter(confirmed, 'mojo').to('chia').toString()
        global_balance = parseFloat(Number(chia_confirmed))

        balance_textfield.innerHTML = "Your available balance is " + chia_confirmed + " CH"
      }
    }

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

        if (command == "start_server") {
            get_wallets();
        } else if (command == "get_wallet_balance") {
            get_wallet_balance_response(data);
        } else if (command == "get_wallets") {
            get_wallets_response(data)
        } else if (command == "create_new_wallet") {
            create_wallet_response(data);
        }
    });

    socket.on('error', function clear() {
        console.log("Not connected, reconnecting");
        connect(1000);
    });
}

set_callbacks(ws);

async function connect(timeout) {
    /*
    Tries to connect to the host after a timeout
    */
    await sleep(timeout);
    ws = new WebSocket(wallet_rpc_host_and_port);
    set_callbacks(ws);
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

function get_wallets() {
    /*
    Sends websocket request to get list of all wallets available
    */
    data = {
        "command": "get_wallets",
    }
    json_data = JSON.stringify(data);
    ws.send(json_data);
}

function get_wallets_response(data) {
    const wallets = data["wallets"]

    for (var i = 0; i < wallets.length; i++) {
        var wallet = wallets[i];
        var type = wallet["type"]
        var id = wallet["id"]
        var name = wallet["name"]
        //href, wallet_name, wallet_description, wallet_amount
        var href = ""
        if (type == "STANDARD_WALLET") {
            get_wallet_balance(id)
            href = "wallet-dark.html"
        } else if (type == "RATE_LIMITED") {
            href = "rl_wallet/rl_wallet.html"
        } else if (type == "COLOURED_COIN") {
            href = "cc_wallet/cc_wallet.html"
        }
      }
    }
