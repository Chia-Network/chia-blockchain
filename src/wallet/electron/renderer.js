const host = "ws://127.0.0.1:9256"
const jquery = require('jquery')
var QRCode = require('qrcode')
var canvas = document.getElementById('qr_canvas')
const Dialogs = require('dialogs')
const dialogs = Dialogs()
const WebSocket = require('ws');
var ws = new WebSocket(host);
let chia_formatter = require('./chia');

// HTML
let send = document.querySelector('#send')
let farm_button = document.querySelector('#farm_block')
let new_address = document.querySelector('#new_address')
let copy = document.querySelector("#copy")
let receiver_address = document.querySelector("#receiver_puzzle_hash")
let amount = document.querySelector("#amount_to_send")
let table = document.querySelector("#tx_table").getElementsByTagName('tbody')[0]
let balance_textfield = document.querySelector('#balance_textfield')
let pending_textfield = document.querySelector('#pending_textfield')
let connection_textfield = document.querySelector('#connection_textfield')
let syncing_textfield = document.querySelector('#syncing_textfield')
let block_height_textfield = document.querySelector('#block_height_textfield')
let standard_wallet_balance = document.querySelector('#standard_wallet_balance')

// UI checkmarks and lock icons
const green_checkmark = "<i class=\"icon ion-md-checkmark-circle-outline green\"></i>"
const red_checkmark = "<i class=\"icon ion-md-close-circle-outline red\"></i>"
const lock = "<i class=\"icon ion-md-lock\"></i>"

// Global variables
var global_syncing = true


console.log(global.location.search)
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
console.log("testing: " + local_test)

if (local_test == "false") {
    console.log("farm_button should be hidden")
    farm_button.style.visibility="hidden"
}

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
            console.log("Received message data: " + JSON.stringify(data));
        }

        if (command == "start_server") {
            get_new_puzzlehash();
            get_transactions();
            get_wallet_balance();
            get_height_info();
            get_sync_status();
            get_connection_info();
            connection_checker();
        } else if (command == "get_next_puzzle_hash") {
            get_new_puzzlehash_response(data);
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
    puzzlehash = receiver_address.value;
    amount_value = parseFloat(amount.value);
    mojo_amount = chia_formatter(amount_value, 'chia').to('mojo')
    console.log("Mojo amount: " + mojo_amount);

    data = {
        "puzzlehash": puzzlehash,
        "amount": mojo_amount
    }

    request = {
        "command": "send_transaction",
        "data": data
    }
    json_data = JSON.stringify(request);
    ws.send(json_data);
})

farm_button.addEventListener('click', () => {
    /*
    Called when send button in ui is pressed.
    */
    console.log("farm block")
    puzzle_hash = receiver_address.value;
    if (puzzle_hash == "") {
        dialogs.alert("Specify puzzle_hash for coinbase reward", ok => {
        })
        return
    }
    data = {
        "puzzle_hash": puzzle_hash,
    }
    request = {
        "command": "farm_block",
        "data": data
    }
    json_data = JSON.stringify(request);
    ws.send(json_data);
    //dialogs.alert("Farmed new block!", ok => {});
})

function send_transaction_response(response) {
    /*
    Called when response is received for send_transaction request
    */
    console.log(JSON.stringify(response));
    success = response["success"];
    if (!success) {
        dialogs.alert("You don\'t have enough chia for this transactions", ok => {
        })
        return
    }
}

new_address.addEventListener('click', () => {
    /*
    Called when new address button is pressed.
    */
    console.log("new address requesting");
    get_new_puzzlehash(0);
})

copy.addEventListener("click", () => {
    /*
    Called when copy button is pressed
    */
    let puzzle_holder = document.querySelector("#puzzle_holder");
    puzzle_holder.select();
    /* Copy the text inside the text field */
    document.execCommand("copy");
})

async function get_new_puzzlehash() {
    /*
    Sends websocket request for new puzzle_hash
    */
    data = {
        "command": "get_next_puzzle_hash",
    }
    json_data = JSON.stringify(data);
    ws.send(json_data);
}

function get_new_puzzlehash_response(response) {
    /*
    Called when response is received for get_new_puzzle_hash request
    */
    let puzzle_holder = document.querySelector("#puzzle_holder");
    puzzle_holder.value = response["puzzlehash"];
    QRCode.toCanvas(canvas, response["puzzlehash"], function (error) {
    if (error) console.error(error)
    console.log('success!');
    })
}

async function get_wallet_balance() {
    /*
    Sends websocket request to get wallet balance
    */
    data = {
        "command": "get_wallet_balance",
    }
    json_data = JSON.stringify(data);
    ws.send(json_data);
}

function get_wallet_balance_response(response) {
    console.log("update balance" + response);
    if (response["success"]) {
        var confirmed = parseInt(response["confirmed_wallet_balance"])
        var unconfirmed = parseInt(response["unconfirmed_wallet_balance"])
        var pending = confirmed - unconfirmed
        chia_confirmed = chia_formatter(confirmed, 'mojo').to('chia').toString()
        chia_pending = chia_formatter(pending, 'mojo').to('chia').toString()

        balance_textfield.innerHTML = chia_confirmed
        standard_wallet_balance.innerHTML = chia_confirmed.toString() + " CH"
        standard_wallet_balance.innerHTML = chia_confirmed.toString() + " CH"
        if (pending > 0) {
            pending_textfield.innerHTML = lock + " - " + chia_pending + " CH"
            standard_wallet_pending.innerHTML = lock + " - " + chia_pending + " CH"
        } else {
            pending_textfield.innerHTML = lock + " " + chia_pending + " CH"
            standard_wallet_pending.innerHTML = lock + " - " + chia_pending + " CH"
        }
    }
}

async function get_transactions() {
    /*
    Sends websocket request to get transactions
    */
    data = {
        "command": "get_transactions",
    }
    json_data = JSON.stringify(data);
    ws.send(json_data);
}

function get_transactions_response(response) {
    /*
    Called when response is received for get_transactions request
    */
    clean_table()

    for (var i = 0; i < response.txs.length; i++) {
        var tx = JSON.parse(response.txs[i]);
        //console.log(tx);
        var row = table.insertRow(0);
        var cell_type = row.insertCell(0);
        var cell_to = row.insertCell(1);
        var cell_date = row.insertCell(2);
        var cell_status = row.insertCell(3);
        var cell_amount = row.insertCell(4);
        var cell_fee = row.insertCell(5);
        //type of transaction
        if (tx["incoming"]) {
            cell_type.innerHTML = "Incoming";
        } else {
            cell_type.innerHTML = "Outgoing";
        }
        // Receiving puzzle hash
        cell_to.innerHTML = tx["to_puzzle_hash"];

        // Date
        var date = new Date(parseInt(tx["created_at_time"]) * 1000);
        cell_date.innerHTML = "" + date;

        // Confirmation status
        if (tx["confirmed"]) {
             index = tx["confirmed_at_index"];
             cell_status.innerHTML = "Confirmed" + green_checkmark +"</br>" + "Block: " + index;
        } else {
             cell_status.innerHTML = "Pending " + red_checkmark;
        }

        // Amount and Fee
        var amount = parseInt(tx["amount"])
        var fee = parseInt(tx["fee_amount"])
        cell_amount.innerHTML = " " + chia_formatter(amount, 'mojo').to('chia').toString() + " CH"
        cell_fee.innerHTML = " " + chia_formatter(fee, 'mojo').to('chia').toString() + " CH"
    }
}

async function get_height_info() {
    /*
    Sends websocket request to blockchain height
    */
    data = {
        "command": "get_height_info",
    }
    json_data = JSON.stringify(data);
    ws.send(json_data);
}

async function get_sync_status() {
    /*
    Sends websocket request to see if wallet is syncing currently
    */
    data = {
        "command": "get_sync_status",
    }
    json_data = JSON.stringify(data);
    ws.send(json_data);
}

async function connection_checker() {
    await sleep(10000);
    await get_connection_info()
    connection_checker()
}

async function get_connection_info() {
    /*
    Sends websocket request to get list of connections
    */
    data = {
        "command": "get_connection_info",
    }
    json_data = JSON.stringify(data);
    ws.send(json_data);
}

function get_height_info_response(response) {
    height = response["height"]
    console.log("height is " + height)
    block_height_textfield.innerHTML = "" + height;
}

function get_sync_status_response(response) {
    syncing = response["syncing"]
    console.log("Syncing: " + syncing)
    global_syncing = syncing
    if (syncing) {
        syncing_textfield.innerHTML = "Syncing in progress";
    } else {
        syncing_textfield.innerHTML = "Synced";
    }
}

async function get_connection_info_response(response) {
    connections = response["connections"]
    console.log("Connections:" + connections)
    console.log("Connected to: " + connections.length + " peers")
    count = connections.length;
    if (count == 0) {
        connection_textfield.innerHTML = "Not Connected!!!"
    } else if (count == 1) {
        connection_textfield.innerHTML = connections.length + " connection"
    } else {
        connection_textfield.innerHTML = connections.length + " connections"
    }
}

function handle_state_changed(data) {
    state = data["state"]
    if (state == "coin_removed") {
        get_transactions()
        get_wallet_balance()
    } else if (state == "coin_added") {
        get_transactions()
        get_wallet_balance()
    } else if (state == "pending_transaction") {
        get_transactions()
        get_wallet_balance()
    } else if (state == "tx_sent") {
        get_transactions()
        get_wallet_balance()
        dialogs.alert("Transaction sent successfully!", ok => {});
    } else if (state == "balance_changed") {
        get_wallet_balance()
    } else if (state == "sync_changed") {
        get_sync_status()
    } else if (state == "new_block") {
        get_height_info()
    } else if (state == "reorg") {
        get_transactions()
        get_wallet_balance()
        get_height_info()
        get_sync_status()
    }
}

function clean_table() {
    while (table.rows.length > 0) {
        table.deleteRow(0);
    }
}

clean_table();
