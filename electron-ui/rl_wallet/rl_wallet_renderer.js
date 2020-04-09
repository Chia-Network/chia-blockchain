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
let connection_textfield = document.querySelector('#connection_textfield')
let syncing_textfield = document.querySelector('#syncing_textfield')
let block_height_textfield = document.querySelector('#block_height_textfield')
let wallets_tab = document.querySelector('#wallets_tab')
let admin_setup = document.querySelector('#admin_setup')
let user_setup = document.querySelector('#user_setup')
let admin_wallet = document.querySelector("#admin_wallet")
let user_wallet = document.querySelector("#user_wallet")
let copy_user_public_key = document.querySelector("#copy_user_public_key")
let copy_admin_public_key = document.querySelector("#copy_admin_public_key")
let wallet_copy_admin_public_key = document.querySelector("#wallet_copy_admin_public_key")
let admin_copy_origin_id = document.querySelector("#admin_copy_origin_id")

// UI checkmarks and lock icons
const green_checkmark = "<i class=\"icon ion-md-checkmark-circle-outline green\"></i>"
const red_checkmark = "<i class=\"icon ion-md-close-circle-outline red\"></i>"
const lock = "<i class=\"icon ion-md-lock\"></i>"

// Global variables
var global_syncing = true
console.log(global.location.search)
global_my_config = null

function create_side_wallet(id, href, wallet_name, wallet_description, wallet_amount, active) {
    var balance_id = "balance_wallet_" + id
    var pending_id = "pending_wallet_" + id
    href += "?wallet_id=" + id + "&testing=" + local_test
    var is_active = active ? "active" : "";
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
        } else if (command == "rl_set_admin_info") {
            rl_set_admin_info_response(data)
        } else if (command == "rl_set_user_info") {
            rl_set_user_info_response(data)
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
    puzzle_hash = receiver_address.value;
    amount_value = parseFloat(amount.value);
    mojo_amount = chia_formatter(amount_value, 'chia').to('mojo').value()
    console.log("Mojo amount: " + mojo_amount);

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
})

function send_transaction_response(response) {
    /*
    Called when response is received for send_transaction request
    */
    console.log(JSON.stringify(response));
    status = response["status"];
    if (status === "SUCCESS") {
        dialogs.alert("Transaction accepted succesfully into the mempool.", ok => {});
    } else if (status === "PENDING") {
        dialogs.alert("Transaction is pending acceptance into the mempool. Reason: " + response["reason"], ok => {});
    } else if (status === "FAILED") {
        dialogs.alert("Transaction failed. Reason: " + response["reason"], ok => {});
    }
}


copy_admin_public_key.addEventListener("click", () => {
    /*
    Called when copy button is pressed
    */
    let textfield = document.querySelector("#admin_public_key");
    textfield.select();
    /* Copy the text inside the text field */
    document.execCommand("copy");
})

wallet_copy_admin_public_key.addEventListener("click", () => {
    /*
    Called when copy button is pressed
    */
    let textfield = document.querySelector("#wallet_admin_public_key");
    textfield.select();
    /* Copy the text inside the text field */
    document.execCommand("copy");
})

admin_copy_origin_id.addEventListener("click", () => {
    /*
    Called when copy button is pressed
    */
    let textfield = document.querySelector("#admin_origin_id");
    textfield.select();
    /* Copy the text inside the text field */
    document.execCommand("copy");
})

copy_user_public_key.addEventListener("click", () => {
    /*
    Called when copy button is pressed
    */
    let textfield = document.querySelector("#user_public_key");
    textfield.select();
    /* Copy the text inside the text field */
    document.execCommand("copy");
})

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
    console.log("update balance" + JSON.stringify(response));
    if (response["success"]) {
        var confirmed = parseInt(response["confirmed_wallet_balance"])
        var unconfirmed = parseInt(response["unconfirmed_wallet_balance"])
        var pending = confirmed - unconfirmed
        var wallet_id = response["wallet_id"]

        chia_confirmed = chia_formatter(confirmed, 'mojo').to('chia').toString()
        chia_pending = chia_formatter(pending, 'mojo').to('chia').toString()

        wallet_balance_holder = document.querySelector("#" + "balance_wallet_" + wallet_id )
        wallet_pending_holder = document.querySelector("#" + "pending_wallet_" + wallet_id )

        if (g_wallet_id == wallet_id) {
            balance_textfield.innerHTML = chia_confirmed
            if (pending > 0) {
                pending_textfield.innerHTML = lock + " - " + chia_pending + " CH"
            } else {
                pending_textfield.innerHTML = lock + " " + chia_pending + " CH"
            }
        }
        if (wallet_balance_holder) {
            wallet_balance_holder.innerHTML = chia_confirmed.toString() + " CH"
        }
        if (wallet_pending_holder) {
            if (pending > 0) {
                wallet_pending_holder.innerHTML = lock + " - " + chia_pending + " CH"
            } else {
                wallet_pending_holder.innerHTML = lock + " " + chia_pending + " CH"
            }
        }
    }
}

async function get_transactions() {
    /*
    Sends websocket request to get transactions
    */

    data = {
        "wallet_id": g_wallet_id,
    }

    request = {
        "command": "get_transactions",
        "data": data,
    }

    json_data = JSON.stringify(request);
    ws.send(json_data);
}

var glob_counter = 0

function get_transactions_response(response) {
    /*
    Called when response is received for get_transactions request
    */
    if (global_syncing) {
        glob_counter++;
        if ((glob_counter % 10) == 0) {

        } else {
            return
        }
    }
    return
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
        get_transactions()
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
    if(global_syncing) {
        get_wallet_balance(g_wallet_id)
        get_sync_status()
        get_height_info()
        return;
    }

    if (state == "coin_removed") {
        get_transactions()
        get_wallet_balance(g_wallet_id)
    } else if (state == "coin_added") {
        get_transactions()
        get_wallet_balance(g_wallet_id)
    } else if (state == "pending_transaction") {
        get_transactions()
        get_wallet_balance(g_wallet_id)
    } else if (state == "tx_sent") {
        get_transactions()
        get_wallet_balance(g_wallet_id)
    } else if (state == "balance_changed") {
        get_wallet_balance(g_wallet_id)
    } else if (state == "sync_changed") {
        get_sync_status()
    } else if (state == "new_block") {
        get_height_info()
    } else if (state == "reorg") {
        get_transactions()
        get_wallet_balance(g_wallet_id)
        get_height_info()
        get_sync_status()
    }
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

function set_admin_create_button(button) {
    button.addEventListener('click', () => {
    /*
    Called when create contract in admin mode was clicked
    */
    user_pubkey = document.querySelector("#admin_user_public_key").value
    limit = document.querySelector("#admin_amount_per_interval").value
    interval = document.querySelector("#admin_time_interval").value
    amount = document.querySelector("#admin_amount_to_send").value

    if (user_pubkey == "" || limit == "" || interval == "" || amount == "") {
        dialogs.alert("Please fill all fields", ok => {
        })
        return
    }
    mojo_amount = chia_formatter(parseFloat(amount), 'chia').to('mojo').value()
    mojo_limit = chia_formatter(parseFloat(limit), 'chia').to('mojo').value()
    data = {
        "wallet_id": g_wallet_id,
        "user_pubkey": user_pubkey,
        "limit": mojo_limit,
        "interval": interval,
        "amount": mojo_amount,
    }
    request = {
        "command": "rl_set_admin_info",
        "data": data
    }
    json_data = JSON.stringify(request);
    ws.send(json_data);

    })
}

function rl_set_admin_info_response(data) {
    console.log("Data is:" + data)
    if (data["success"] == true) {
        reload()
    } else {
        dialogs.alert("Failed to create RL smart contract, check if you have enough chia available.", ok => {
        })
    }
}

function set_user_create_button(button) {
    button.addEventListener('click', () => {
    /*
    Called when create contract in user mode was clicked
    */
    admin_pubkey = document.querySelector("#user_admin_public_key").value
    limit = document.querySelector("#user_amount_per_interval").value
    interval = document.querySelector("#user_time_interval").value

    if (admin_pubkey == "" || limit == "" || interval == "") {
        dialogs.alert("Please fill all fields", ok => {
        })
        return
    }

    mojo_limit = chia_formatter(parseFloat(limit), 'chia').to('mojo').value()
    data = {
        "wallet_id": g_wallet_id,
        "admin_pubkey": admin_pubkey,
        "limit": mojo_limit,
        "interval": interval,
    }

    request = {
        "command": "rl_set_user_info",
        "data": data
    }
    json_data = JSON.stringify(request);
    ws.send(json_data);

    })
}

function render_wallet_config() {
    type = global_my_config["type"]
    admin_pubkey = global_my_config["admin_pubkey"]
    user_pubkey = global_my_config["user_pubkey"]
    limit = global_my_config["limit"]
    interval = global_my_config["interval"]
    rl_origin_id = global_my_config["rl_origin_id"]
    console.log("type: " + type)
    if (type == "admin") {
        if (user_pubkey == null || limit == null || interval == null || rl_origin_id == null) {
            // Render Admin Setup
            console.log("Render Admin Setup")
            document.querySelector("#admin_public_key").value = global_my_config["admin_pubkey"]
            set_admin_create_button(document.querySelector("#admin_create_button"))
            admin_setup.classList.remove("hidden_area");
        } else {
            // Render admin wallet
            console.log("Render Admin Wallet")
            limit_chia = chia_formatter(parseInt(limit), 'mojo').to('chia').toString()
            admin_wallet.classList.remove("hidden_area");
            document.querySelector("#admin_rate_limit").innerHTML = limit_chia + " CH / " + interval + " Blocks"
            document.querySelector("#admin_user_puzzle_hash").value = global_my_config["rl_puzzle_hash"]
            document.querySelector("#admin_public_key").value = global_my_config["admin_pubkey"]
            document.querySelector("#wallet_admin_public_key").value = global_my_config["admin_pubkey"]
            document.querySelector("#admin_origin_id").value = global_my_config["rl_origin_id"]
        }
    } else if (type == "user") {
        if (admin_pubkey == null || limit == null || interval == null || rl_origin_id == null) {
            // Render User Setup
            limit_chia = chia_formatter(parseInt(limit), 'mojo').to('chia').toString()
            document.querySelector("#user_public_key").value = global_my_config["user_pubkey"]
            user_setup.classList.remove("hidden_area");
            console.log("Render User Setup")
        } else {
            // Render user wallet
            console.log("Render Admin Wallet")
            user_wallet.classList.remove("hidden_area");
        }
    }
}

function get_wallets_response(data) {
    wallets_tab.innerHTML = ""
    new_innerHTML = ""
    const wallets = data["wallets"]
    console.log("received wallets" + wallets)

    for (var i = 0; i < wallets.length; i++) {
        var wallet = JSON.parse(wallets[i]);
        var type = wallet["type"]
        var id = wallet["id"]
        var name = wallet["name"]
        get_wallet_balance(id)
        //href, wallet_name, wallet_description, wallet_amount
        var href = ""
        if (type == "STANDARD_WALLET") {
            href = "../wallet-dark.html"
        } else if (type == "RATE_LIMITED") {
            href = "./rl_wallet.html"
        }

        console.log(wallet)
        if (id == g_wallet_id) {
            my_wallet_info = JSON.parse(wallet["data"])
            console.log(wallet["data"])
            global_my_config = my_wallet_info
            render_wallet_config()
            new_innerHTML += create_side_wallet(id, href, name, type, 0, true)
        } else {
            new_innerHTML += create_side_wallet(id, href, name, type, 0, false)
        }

    }
    new_innerHTML += create_wallet_button()
    wallets_tab.innerHTML = new_innerHTML
}

function clean_table(table) {
    while (table.rows.length > 0) {
        table.deleteRow(0);
    }
}

function reload(){

    newWindow = electron.remote.getCurrentWindow()

    query = "?testing="+local_test + "&wallet_id=" + g_wallet_id
    newWindow.loadURL(require('url').format({
    pathname: path.join(__dirname, "../wallet-dark.html"),
    protocol: 'file:',
    slashes: true
    }) + query
    )

    newWindow.once('ready-to-show', function (){
        newWindow.show();
    });

    newWindow.on('closed', function() {
        newWindow = null;
    });
}

