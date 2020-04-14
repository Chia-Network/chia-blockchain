const host = "ws://127.0.0.1:9256"
var QRCode = require('qrcode')
var canvas = document.getElementById('qr_canvas')
const Dialogs = require('dialogs')
const dialogs = Dialogs()
const WebSocket = require('ws');
var ws = new WebSocket(host);
let chia_formatter = require('../chia');
const electron = require('electron')
const path = require('path')
const { get_query_variable } = require("../utils");

// HTML
let syncing_textfield = document.querySelector('#syncing_textfield')
let block_height_textfield = document.querySelector('#block_height_textfield')
let connection_textfield = document.querySelector('#connection_textfield')
let wallets_tab = document.querySelector('#wallets_tab')
let set_name_button = document.querySelector('#set_name_button')

// UI checkmarks and lock icons
const green_checkmark = "<i class=\"icon ion-md-checkmark-circle-outline green\"></i>"
const red_checkmark = "<i class=\"icon ion-md-close-circle-outline red\"></i>"
const lock = "<i class=\"icon ion-md-lock\"></i>"

// Global variables
var global_syncing = true

function create_side_wallet(id, href, wallet_name, wallet_description, wallet_amount, active) {
    var balance_id = "balance_wallet_" + id
    var pending_id = "pending_wallet_" + id
    var is_active = active ? "active" : "";
    href += "?wallet_id=" + id + "&testing=" + local_test
    const template = `<a class="nav-link d-flex justify-content-between align-items-center ${is_active}" data-toggle="pill"
              href="${href}" role="tab" aria-selected="true">
              <div class="d-flex">
                <img src="../assets/img/circle-cropped.png" alt="btc">
                <div>
                  <h2>${wallet_name}</h2>
                  <p>${wallet_description}</p>
                </div>
              </div>
              <div>
                <p class="text-right" id="${balance_id}">0.00</p>
                <p class="text-right" id="${pending_id}"><i class="icon ion-md-lock"></i> 0.00</p>
              </div>
            </a>`
    return template
}

function create_wallet_button() {
    create_button = `<a class="nav-link d-flex justify-content-between align-items-center" data-toggle="pill" href="../create_wallet.html"
              role="tab" aria-selected="true">
              <div class="d-flex">
                <div>
                  <h2> + Create New Wallet</h2>
                </div>
              </div>
              <div>
                <p class="text-right"><i class="icon ion-md-plus"></i></p>
              </div>
            </a>`
    return create_button
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
        if (data) {
            //console.log("Received message data: " + JSON.stringify(data));
        }

        if (command == "start_server") {
            get_wallets();
            get_height_info();
            get_sync_status();
            get_connection_info();
            connection_checker();
        } else if (command == "get_wallet_balance") {
            get_wallet_balance_response(data);
        } else if (command == "send_transaction") {
            send_transaction_response(data);
        } else if (command == "get_transactions") {
            get_transactions_response(data);
        } else if (command == "state_changed") {
            handle_state_changed(data);
        } else if (command == "get_connection_info") {
            get_connection_info_response(data)
        } else if (command == "get_height_info") {
            get_height_info_response(data)
        } else if (command == "get_sync_status") {
            get_sync_status_response(data)
        } else if (command == "get_wallets") {
            get_wallets_response(data)
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

send.addEventListener('click', () => {
    /*
    Called when send button in ui is pressed.
    */

    if (global_syncing) {
        dialogs.alert("Can't send transactions while syncing.", ok => {});
        return
    }
    if (global_sending_transaction) {
        return;
    }

    try {
        puzzle_hash = receiver_address.value;
        if (puzzle_hash.startsWith("0x") || puzzle_hash.startsWith("0X")) {
            puzzle_hash = puzzle_hash.substring(2);
        }
        if (puzzle_hash.length != 64) {
            alert("Please enter a 32 byte puzzle hash in hexadecimal format");
            return;
        }
        amount_value = parseFloat(Number(amount.value));
        if (isNaN(amount_value)) {
            alert("Please enter a valid numeric amount");
            return;
        }
        global_sending_transaction = true;
        send.disabled = true;
        send.innerHTML = "SENDING...";
        mojo_amount = chia_formatter(amount_value, 'chia').to('mojo').value()

        data = {
            "puzzle_hash": puzzle_hash,
            "amount": mojo_amount,
            "wallet_id": g_wallet_id
        }

        request = {
            "command": "send_transaction",
            "data": data
        }
        json_data = JSON.stringify(request);
        ws.send(json_data);
    } catch (error) {
        alert("Error sending the transaction").
        global_sending_transaction = false;
        send.disabled = false;
        send.innerHTML = "SEND";
    }
})

function send_transaction_response(response) {
    /*
    Called when response is received for send_transaction request
    */
   console.log(JSON.stringify(response));
   status = response["status"];
   if (status === "SUCCESS") {
       dialogs.alert("Transaction accepted succesfully into the mempool.", ok => {});
       receiver_address.value = "";
       amount.value = "";
   } else if (status === "PENDING") {
       dialogs.alert("Transaction is pending acceptance into the mempool. Reason: " + response["reason"], ok => {});
       receiver_address.value = "";
       amount.value = "";
   } else if (status === "FAILED") {
       dialogs.alert("Transaction failed. Reason: " + response["reason"], ok => {});
   }
    global_sending_transaction = false;
    send.disabled = false;
    send.innerHTML = "SEND";
}


function get_wallets_response(data) {
    wallets_tab.innerHTML = ""
    new_innerHTML = ""
    const wallets = data["wallets"]

    for (var i = 0; i < wallets.length; i++) {
        var wallet = wallets[i];
        var type = wallet["type"]
        var id = wallet["id"]
        var name = wallet["name"]
        get_wallet_balance(id)
        //href, wallet_name, wallet_description, wallet_amount
        var href = ""
        if (type == "STANDARD_WALLET") {
            href = "wallet-dark.html"
        } else if (type == "RATE_LIMITED") {
            href = "rl_wallet/rl_wallet.html"
        } else if (type == "COLOURED_COIN") {
            href = "cc_wallet/cc_wallet.html"
        }

        if (id == g_wallet_id) {
            new_innerHTML += create_side_wallet(id, href, name, type, 0, true)
        } else {
            new_innerHTML += create_side_wallet(id, href, name, type, 0, false)
        }

    }
    new_innerHTML += create_wallet_button()
    wallets_tab.innerHTML = new_innerHTML
}

set_name_button.addEventListener('click', () => {
    /*
    Called when set name button in ui is pressed.
    */

    name = document.querySelector("#set_name_input").value
    console.log("update colored coin wallet name to" + JSON.stringify(name)");
    data = {
        "wallet_id": g_wallet_id,
        "name": name,
    }
    request = {
        "command": "cc_set_name",
        "data": data
    }
    json_data = JSON.stringify(request);
    ws.send(json_data);
}

function set_name_response(data) {
    console.log("Data is:" + data)
    if (data["success"] == true) {
        reload()
    } else {
        dialogs.alert("Failed to set the name.", ok => {
        })
    }
}

function get_name() {
    /*
    Gets the custom CC color name
    */
    data = {
        "command": "cc_get_name",
    }
    json_data = JSON.stringify(data);
    ws.send(json_data);
}
