const { wallet_rpc_host_and_port } = require("./config");
var QRCode = require('qrcode')
var canvas = document.getElementById('qr_canvas')
const Dialogs = require('dialogs')
const dialogs = Dialogs()
const WebSocket = require('ws');
let chia_formatter = require('./chia');
const electron = require('electron')
var offer_file_holder = ""
var offer_file_path = ""


// HTML
let top_link = document.querySelector('#top_link')
let send = document.querySelector('#send')
let farm_button = document.querySelector('#farm_block')
let new_address = document.querySelector('#new_address')
let copy = document.querySelector("#copy")
let receiver_address = document.querySelector("#receiver_puzzle_hash")
let amount = document.querySelector("#amount_to_send")
let connection_textfield = document.querySelector('#connection_textfield')
let syncing_textfield = document.querySelector('#syncing_textfield')
let block_height_textfield = document.querySelector('#block_height_textfield')
let standard_wallet_balance = document.querySelector('#standard_wallet_balance')
let wallets_tab = document.querySelector('#wallets_tab')
const { get_query_variable } = require("./utils");
let select_menu = document.querySelector("#select_menu")
let accept_offer = document.querySelector('#accept_offer')
let decline_offer = document.querySelector('#decline_offer')
let view_offer_parent = document.querySelector('#view_offer_parent')
let drag_parent = document.querySelector('#drag_parent')

// UI checkmarks and lock icons
const green_checkmark = "<i class=\"icon ion-md-checkmark-circle-outline green\"></i>"
const red_checkmark = "<i class=\"icon ion-md-close-circle-outline red\"></i>"
const lock = "<i class=\"icon ion-md-lock\"></i>"

// Global variables
var global_syncing = true
var global_sending_transaction = false

function create_side_wallet(id, href, wallet_name, wallet_description, wallet_amount, active) {
    var balance_id = "balance_wallet_" + id
    var pending_id = "pending_wallet_" + id
    var is_active = active ? "active" : "";
    href += "?wallet_id=" + id + "&testing=" + local_test
    const template = `<a class="nav-link d-flex justify-content-between align-items-center ${is_active}" data-toggle="pill"
              href="${href}" role="tab" aria-selected="true">
              <div class="d-flex">
                <img src="assets/img/circle-cropped.png" alt="btc">
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
    create_button = `<a class="nav-link d-flex justify-content-between align-items-center" data-toggle="pill" href="./create_wallet.html"
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

function create_select_options(options) {
  buy = `<div class="custom-select-s" style="width:45%;float:left;">
  <select>
    <option value="0">Select Buy or Sell</option>
    <option value="1">Buy</option>
    <option value="2">Sell</option>
  </select>
</div>`
  select = `<div class="custom-select-s" style="width:45%;margin-left:50%">
  <select>
  <option value="0">Select Coin</option>
    `
  for (var i = 0; i < options.length; i++) {
    wallet_id = options[i]["id"];
    wallet_name = options[i]["name"]
    select += `<option value="${wallet_id}">${wallet_name}</option>`
  }
  select += `</select>
    </div>`

  console.log(select)
  return buy + select
}

var local_test = electron.remote.getGlobal('sharedObj').local_test;

if (local_test == false) {
    farm_button.style.visibility="hidden"
}

function sleep(ms) {
    return new Promise((resolve) => {
        setTimeout(resolve, ms);
    });
}

var ws = new WebSocket(wallet_rpc_host_and_port);

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
        } else if (command == "get_discrepancies_for_offer") {
            get_discrepancies_for_offer_response(data)
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
        chia_pending = chia_formatter(pending, 'mojo').to('chia').toString()

        wallet_balance_holder = document.querySelector("#" + "balance_wallet_" + wallet_id )
        wallet_pending_holder = document.querySelector("#" + "pending_wallet_" + wallet_id )

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

var glob_counter = 0

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
    try {
        await sleep(5000);
        await get_connection_info()
        connection_checker()
    } catch (error) {
        console.error(error);
        connection_textfield.innerHTML = "Not Connected";
        connection_checker()
    }
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
    block_height_textfield.innerHTML = "" + height;
}

function get_sync_status_response(response) {
    syncing = response["syncing"]
    global_syncing = syncing
    if (syncing) {
        syncing_textfield.innerHTML = "Syncing in progress";
    } else {
        syncing_textfield.innerHTML = "Synced";
    }
}

async function get_connection_info_response(response) {
    connections = response["connections"]
    count = connections.length;
    if (count == 0) {
        connection_textfield.innerHTML = "Not Connected"
    } else if (count == 1) {
        connection_textfield.innerHTML = connections.length + " connection"
    } else {
        connection_textfield.innerHTML = connections.length + " connections"
    }
}

function handle_state_changed(data) {
    state = data["state"]
    console.log("State changed", state)
    if(global_syncing) {
        get_wallet_balance(g_wallet_id)
        get_sync_status()
        get_height_info()
        return;
    }

    if (state == "coin_removed") {
        get_wallet_balance(g_wallet_id)
    } else if (state == "coin_added") {
        get_wallet_balance(g_wallet_id)
    } else if (state == "pending_transaction") {
        get_wallet_balance(g_wallet_id)
    } else if (state == "tx_sent") {
        get_wallet_balance(g_wallet_id)
    } else if (state == "balance_changed") {
        get_wallet_balance(g_wallet_id)
    } else if (state == "sync_changed") {
        get_sync_status()
    } else if (state == "new_block") {
        get_height_info()
    } else if (state == "reorg") {
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


        new_innerHTML += create_side_wallet(id, href, name, type, 0, false)

    }
    new_innerHTML += create_wallet_button()
    wallets_tab.innerHTML = new_innerHTML
    select_option = create_select_options(wallets)
    select_menu.innerHTML = select_option
    set_drop_down()
}

function set_drop_down() {
    var x, i, j, selElmnt, a, b, c;
/*look for any elements with the class "custom-select":*/
x = document.getElementsByClassName("custom-select-s");
for (i = 0; i < x.length; i++) {
  selElmnt = x[i].getElementsByTagName("select")[0];
  /*for each element, create a new DIV that will act as the selected item:*/
  a = document.createElement("DIV");
  a.setAttribute("class", "select-selected");
  a.innerHTML = selElmnt.options[selElmnt.selectedIndex].innerHTML;
  x[i].appendChild(a);
  /*for each element, create a new DIV that will contain the option list:*/
  b = document.createElement("DIV");
  b.setAttribute("class", "select-items select-hide");
  for (j = 1; j < selElmnt.length; j++) {
    /*for each option in the original select element,
    create a new DIV that will act as an option item:*/
    c = document.createElement("DIV");
    c.innerHTML = selElmnt.options[j].innerHTML;
    c.addEventListener("click", function(e) {
        /*when an item is clicked, update the original select box,
        and the selected item:*/
        var y, i, k, s, h;
        s = this.parentNode.parentNode.getElementsByTagName("select")[0];
        h = this.parentNode.previousSibling;
        for (i = 0; i < s.length; i++) {
          if (s.options[i].innerHTML == this.innerHTML) {
            s.selectedIndex = i;
            h.innerHTML = this.innerHTML;
            y = this.parentNode.getElementsByClassName("same-as-selected");
            for (k = 0; k < y.length; k++) {
              y[k].removeAttribute("class");
            }
            this.setAttribute("class", "same-as-selected");
            break;
          }
        }
        h.click();
    });
    b.appendChild(c);
  }
  x[i].appendChild(b);
  a.addEventListener("click", function(e) {
      /*when the select box is clicked, close any other select boxes,
      and open/close the current select box:*/
      e.stopPropagation();
      closeAllSelect(this);
      this.nextSibling.classList.toggle("select-hide");
      this.classList.toggle("select-arrow-active");
    });
}
}

function closeAllSelect(elmnt) {
  /*a function that will close all select boxes in the document,
  except the current select box:*/
  var x, y, i, arrNo = [];
  x = document.getElementsByClassName("select-items");
  y = document.getElementsByClassName("select-selected");
  for (i = 0; i < y.length; i++) {
    if (elmnt == y[i]) {
      arrNo.push(i)
    } else {
      y[i].classList.remove("select-arrow-active");
    }
  }
  for (i = 0; i < x.length; i++) {
    if (arrNo.indexOf(i)) {
      x[i].classList.add("select-hide");
    }
  }
}
/*if the user clicks anywhere outside the select box,
then close all select boxes:*/
document.addEventListener("click", closeAllSelect);
let drag_status = document.querySelector('#drag-status')


function create_drag() {
    holder = document.getElementById('drag-drop')

    holder.ondragover = () => {
        return false;
    };

    holder.ondragleave = () => {
        return false;
    };

    holder.ondragend = () => {
        return false;
    };

    holder.ondrop = (e) => {
        e.preventDefault();

        for (let f of e.dataTransfer.files) {
            console.log('File(s) you dragged here: ', f.path)
        }

        if (global_syncing) {
            dialogs.alert("Can't view offers while syncing.", ok => {});
            return
        }

        offer_file_path =  e.dataTransfer.files[0].path
        offer_file_holder = offer_file_path.replace(/^.*[\\\/]/, '')
        console.log(offer_file_path)
        drag_status.innerHTML = "Parsing Offer...";

        data = {
            "filename": offer_file_path,
        }

        request = {
            "command": "get_discrepancies_for_offer",
            "data": data,
        }

        json_data = JSON.stringify(request);
        ws.send(json_data);

        return false;
    };
}
create_drag()

function get_discrepancies_for_offer_response(response) {
     /*
     Called when response is received for create_offer_for_ids request
     */
     status = response["success"];
     if (status === "true") {
       drag_status.innerHTML = "Drag & Drop offer file";
       offer_dict = response["discrepancies"]
       console.log(offer_dict)
       display_offer(offer_dict)
     } else if (status === "false") {
         dialogs.alert("Error viewing offer. Reason: " + response["error"], ok => {});
         drag_status.innerHTML = "Drag & Drop offer file";
     }
}

trade_offer_holder =  document.querySelector('#view_offer')

function display_offer(dict) {
  view_offer_parent.classList.remove("hidden_area");
  drag_parent.classList.add("hidden_area");

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


decline_offer.addEventListener('click', () => {
    /*
    Called when decline_offer button in ui is pressed.
    */
    view_offer_parent.classList.add("hidden_area");
    drag_parent.classList.remove("hidden_area");

    go_to_main_wallet();
})

accept_offer.addEventListener('click', () => {
    /*
    Called when accept_offer button in ui is pressed.
    */

    accept_offer.disabled = true;
    decline_offer.disabled = true;
    accept_offer.innerHTML = "ACCEPTING...";
    data = {
        "filename": offer_file_path,
    }

    request = {
        "command": "respond_to_offer",
        "data": data,
    }

    json_data = JSON.stringify(request);
    ws.send(json_data);
})


