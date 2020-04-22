const { wallet_rpc_host_and_port } = require("../config");
const Dialogs = require('dialogs')
const dialogs = Dialogs()
const WebSocket = require('ws');
let chia_formatter = require('../chia');
const electron = require('electron')
const { get_query_variable } = require("../utils");
const path = require('path')

// HTML
let view_offer = document.querySelector('#view_offer')
let trade_offer_holder = document.querySelector('#trade_offer_holder')
let accept_offer = document.querySelector('#accept_offer')
let decline_offer = document.querySelector('#decline_offer')

// Global variables
var global_syncing = true
var local_test = electron.remote.getGlobal('sharedObj').local_test;
var wallets_details = {}
var offer_file_holder = "Test Offer"
var ws = new WebSocket(wallet_rpc_host_and_port);
var test_response = {"success": true, "discrepencies": {"12345": 20, "67890": -10, None: 5}}

accept_offer.disabled = true;
decline_offer.disabled = true;

console.log("testing: " + local_test)

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
            get_sync_status();
            get_wallet_summaries();
            //get_discrepancies_for_offer_response(test_response);
        } else if (command == "get_sync_status") {
            get_sync_status_response(data);
        } else if (command == "state_changed") {
            handle_state_changed(data);
        } else if (command == "get_wallet_summaries") {
            get_wallet_summaries_response(data)
        } else if (command == "get_discrepancies_for_offer") {
            get_discrepancies_for_offer_response(data)
        } else if (command == "respond_to_offer") {
            respond_to_offer_response(data)
        }
    });

    socket.on('error', function clear() {
        console.log("Not connected, reconnecting");
        connect(1000);
    });
}

set_callbacks(ws);

function handle_state_changed(data) {
    state = data["state"]
    console.log("State changed", state)
    if(global_syncing) {
        get_sync_status()
        return;
    }
    if (state == "coin_removed") {
        get_wallet_summaries()
    } else if (state == "coin_added") {
        get_wallet_summaries()
    } else if (state == "pending_transaction") {
        get_wallet_summaries()
    } else if (state == "tx_sent") {
        get_wallet_summaries()
    } else if (state == "balance_changed") {
        get_wallet_summaries()
    } else if (state == "sync_changed") {
        get_sync_status()
    } else if (state == "reorg") {
        get_wallet_summaries()
        get_sync_status()
    }
}

async function connect(timeout) {
    /*
    Tries to connect to the host after a timeout
    */
    await sleep(timeout);
    ws = new WebSocket(wallet_rpc_host_and_port);
    set_callbacks(ws);
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

function get_sync_status_response(response) {
    syncing = response["syncing"]
    global_syncing = syncing
}

function go_to_main_wallet() {
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

function get_wallet_summaries() {
  /*
  Sends websocket request to get wallet summaries
  */
  wallets_details = {}
  data = {
      "info": "123",
  }

  request = {
      "command": "get_wallet_summaries",
      "data": data
  }

  json_data = JSON.stringify(request);
  ws.send(json_data);
}

function get_wallet_summaries_response(data){
  // {id: {"type": type, "balance": balance, "name": name, "colour": colour}}
  // {id: {"type": type, "balance": balance}}
  wallets_details = data
  console.log(wallets_details)
}

view_offer.addEventListener('click', () => {
    /*
    Called when view_offer button in ui is pressed.
    */

    if (global_syncing) {
        dialogs.alert("Can't view offers while syncing.", ok => {});
        return
    }

    offer_file = receive_offer_file_path.value;
    filename_suffix = offer_file.slice(offer_file.length - 6);
    if (filename_suffix != ".offer") {
      offer_file = offer_file + ".offer";
    }
    offer_file_holder = offer_file;
    console.log(offer_file)
    view_offer.disabled = true;
    view_offer.innerHTML = "GETTING OFFER...";

    data = {
        "filename": offer_file,
    }

    request = {
        "command": "get_discrepancies_for_offer",
        "data": data,
    }

    json_data = JSON.stringify(request);
    ws.send(json_data);

})

function get_discrepancies_for_offer_response(response) {
     /*
     Called when response is received for create_offer_for_ids request
     */
     status = response["success"];
     if (status === "true") {
       view_offer.disabled = false;
       view_offer.innerHTML = "VIEW OFFER";
       offer_dict = response["discrepancies"]
       console.log(offer_dict)
       display_offer(offer_dict)
     } else if (status === "false") {
         dialogs.alert("Error viewing offer. Reason: " + response["error"], ok => {});
         view_offer.disabled = false;
         view_offer.innerHTML = "VIEW OFFER";
     }
}

function display_offer(dict) {
  trade_offer_holder.innerHTML = ""
  trade_offer_holder_new_innerHTML = `<div class="d-flex" style="padding-top:0px; padding-top:15px; padding-bottom:20px;">
  <h4>${offer_file_holder}</h4>
  </div>`
  for (colour in dict) {
    offer_item_colour = colour
    offer_item_amount = dict[colour]
    offer_item_colour_id = "offer_item_colour_" + offer_item_colour
    offer_item_amount_id = "offer_item_amount_" + offer_item_colour
    const template = `<div class="d-flex" style="padding-top:0px; padding-top:15px;">
    <p id="${offer_item_colour_id}">Colour: ${offer_item_colour}</p>
    </div>
    <div class="input-group" style="padding-top:0px">
    <p id="${offer_item_amount_id}">Amount: ${offer_item_amount}</p>
    </div>/`
    trade_offer_holder_new_innerHTML += template
  }
  accept_offer.disabled = false;
  decline_offer.disabled = false;
  trade_offer_holder.innerHTML = trade_offer_holder_new_innerHTML
}

accept_offer.addEventListener('click', () => {
    /*
    Called when accept_offer button in ui is pressed.
    */

    accept_offer.disabled = true;
    decline_offer.disabled = true;
    accept_offer.innerHTML = "ACCEPTING...";
    data = {
        "filename": offer_file_holder,
    }

    request = {
        "command": "respond_to_offer",
        "data": data,
    }

    json_data = JSON.stringify(request);
    ws.send(json_data);
})

function respond_to_offer_response(response) {
     /*
     Called when response is received for respond_to_offer request
     */
     status = response["success"];
     if (status === "true") {
       //respond_to_offer.innerHTML = "PRINT";
       trade_offer_holder.innerHTML = `<div class="d-flex" style="padding-top:0px; padding-top:15px;">
       <p>Offer successfully accepted.</p>
       </div>/`
     } else if (status === "false") {
       dialogs.alert("Error accepting offer. Reason: " + response["error"], ok => {});
       accept_offer.disabled = false;
       decline_offer.disabled = false;
       accept_offer.innerHTML = "ACCEPT OFFER";
     }
}

decline_offer.addEventListener('click', () => {
    /*
    Called when decline_offer button in ui is pressed.
    */

    accept_offer.disabled = true;
    decline_offer.disabled = true;
    go_to_main_wallet();
})
