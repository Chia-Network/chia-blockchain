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

const { dialog } = require('electron').remote
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
let cancel_offer = document.querySelector('#cancel_offer')
let add_to_offer = document.querySelector('#add_to_offer')
let save_offer = document.querySelector('#save_offer')
let offer_items = document.querySelector('#offer_items')

// UI checkmarks and lock icons
const green_checkmark = "<i class=\"icon ion-md-checkmark-circle-outline green\"></i>"
const red_checkmark = "<i class=\"icon ion-md-close-circle-outline red\"></i>"
const lock = "<i class=\"icon ion-md-lock\"></i>"

// Global variables
var global_syncing = true
var global_sending_transaction = false
var global_wallets = {}
var offer_dictionary = {}
var wallets_details = {}

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

function create_select_options(wallet_summeries) {
  buy = `<div class="custom-select-s" style="width:49%;float:left;">
  <select id="side_selection">
    <option value="0">Select Buy or Sell</option>
    <option value="1">Buy</option>
    <option value="2">Sell</option>
  </select>
</div>`
  select = `<div class="custom-select-s" style="width:49%;margin-left:50%">
  <select id="coin_selection">
  <option value="0">Select Coin</option>
    `
    console.log(wallet_summeries)
  for (key in wallet_summeries) {
    wallet = wallet_summeries[key]
    console.log(wallet)
    if (wallet["type"] == "STANDARD_WALLET") {
        wallet_id = key;
        wallet_name = "Chia"
        select += `<option value="${wallet_id}">${wallet_name}</option>`
    } else {
        wallet_id = key;
        wallet_name = wallet["name"]
        if (wallet_name.length > 32) {
            wallet_name = wallet_name.slice(0, 32) + "...";
        }
        select += `<option class="wrap" value="${wallet_id}">${wallet_name}</option>`
    }
  }
  select += `</select>
    </div>`

  console.log(select)
  return buy + select
}

var local_test = electron.remote.getGlobal('sharedObj').local_test;


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
            get_wallet_summaries()
            //get_wallets();
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
        } else if (command == "get_wallet_summaries") {
            get_wallet_summaries_response(data)
        } else if (command == "create_offer_for_ids") {
            create_offer_for_ids_response(data)
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

async function connect(timeout) {
    /*
    Tries to connect to the host after a timeout
    */
    await sleep(timeout);
    ws = new WebSocket(wallet_rpc_host_and_port);
    set_callbacks(ws);
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
        chia_pending_abs = chia_formatter(Math.abs(pending), 'mojo').to('chia').toString()

        wallet_balance_holder = document.querySelector("#" + "balance_wallet_" + wallet_id )
        wallet_pending_holder = document.querySelector("#" + "pending_wallet_" + wallet_id )

        if (wallet_balance_holder) {
            wallet_balance_holder.innerHTML = chia_confirmed.toString() + " CH"
        }
        if (wallet_pending_holder) {
            if (pending > 0) {
                wallet_pending_holder.innerHTML = lock + " - " + chia_pending + " CH"
            } else {
                wallet_pending_holder.innerHTML = lock + " " + chia_pending_abs + " CH"
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
        get_wallet_summaries()
        get_sync_status()
        get_height_info()
        return;
    }

    if (state == "coin_removed") {
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
    } else if (state == "new_block") {
        get_height_info()
    } else if (state == "reorg") {
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
    global_wallets = wallets
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
        console.log("s" + s.innerHTML)
        console.log("s" + s.id)
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
    <p id="${offer_item_amount_id}">Amount: ${chia_formatter(offer_item_amount, 'mojo').to('chia').toString()}</p>
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
})

accept_offer.addEventListener('click', () => {
    /*
    Called when accept_offer button in ui is pressed.
    */

    accept_offer.disabled = false;
    decline_offer.disabled = false;
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
});

function display_current_offer(){

    dict = offer_dictionary
    template = `<div style="width: 100%; display: table;">`
    for (var key in dict) {
        console.log(key, dict[key]);
        var key = key
        var amount = dict[key]
        var title = ""
        if (amount > 0) {
            title = "Buy"
        } else {
            title = "Sell"
        }
        mojo_abs = Math.abs(amount)
        chia_amount = "Amount: " + chia_formatter(mojo_abs, 'mojo').to('chia').toString() + "    "
        wallet = wallets_details[key]
        name = ""
        if (wallet["type"] == "STANDARD_WALLET") {
            name = "Chia"
        } else {
            name = wallet["name"]
            if (name.length > 16) {
                name = name.slice(0, 16);
            }
        }

        template += `<div style="display: table-row">
                        <div style="padding-left:20px;width: 250px; display: table-cell;"><h2>${title}</h2></div>
                        <div style="padding-left:100px;display: table-cell;"><h2>${chia_amount}</h2></div>
                        <div style="text-align: right;padding-right:15px;display: table-cell;"> <h2>${name}</h2> </div>
                     </div>`
    }

    template += `</div>`

    offer_items.innerHTML = template
}

cancel_offer.addEventListener('click', () => {
    /*
    Called when cancel button in ui is pressed.
    */
    offer_dictionary = {}
    display_current_offer();

});

add_to_offer.addEventListener('click', () => {
    /*
    Called when add button in ui is pressed.
    */
    side =  document.querySelector('#side_selection').value
    coin =  document.querySelector('#coin_selection').value
    amount =  document.querySelector('#amount')
    amount_value = parseFloat(Number(amount.value));
    if (isNaN(amount_value) || amount_value == 0) {
        dialogs.alert("Please enter valid amount", ok => {});
        return;
    }

    mojo_amount = chia_formatter(amount_value, 'chia').to('mojo').value()

    if (side == 0) {
        dialogs.alert("Please select Buy or Sell.", ok => {});
        return
    }
    if (coin == 0) {
        dialogs.alert("Please select type of coin.", ok => {});
        return
    }

    converted_amount = side == 1 ? mojo_amount : - mojo_amount
    offer_dictionary[coin] = converted_amount
    console.log(side)
    console.log(coin)
    console.log(converted_amount)
    amount.value = ""
    select_option = create_select_options(wallets_details)
    select_menu.innerHTML = select_option
    display_current_offer()
    set_drop_down()
})


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
  wallets_details = data
  console.log(data)
  select_option = create_select_options(wallets_details)
  select_menu.innerHTML = select_option
  set_drop_down()
  var new_innerHTML = ""
  for (var i in data) {
      var wallet = data[i];
      var type = wallet["type"]
      var id = i
      var name = wallet["type"]

      get_wallet_balance(id)
      //href, wallet_name, wallet_description, wallet_amount
      var href = ""
      if (type == "STANDARD_WALLET") {
          href = "./wallet-dark.html"
          name = "Chia Wallet"
          type = "Chia"
      } else if (type == "RATE_LIMITED") {
          href = "rl_wallet/rl_wallet.html"
      } else if (type == "COLOURED_COIN") {
          href = "cc_wallet/cc_wallet.html"
          name = "CC Wallet"
          type = wallet["name"]
          if (type.length > 18) {
            type = type.substring(0,18);
            type = type.concat("...")
          }
      }
      new_innerHTML += create_side_wallet(id, href, name, type, 0, false)
  }
  new_innerHTML += create_wallet_button()
  wallets_tab.innerHTML = new_innerHTML
}


save_offer.addEventListener('click', async () => {
  const dialogOptions = {};
  try {
    const result = await dialog.showSaveDialog(dialogOptions);
    const { filePath } = result;
    console.log("saving to: " + filePath)
      offers = offer_dictionary
      console.log(offers)
      save_offer.disabled = true;
      save_offer.innerHTML = "CREATING...";
      data = {
          "ids": offers,
          "filename": filePath
      }

      request = {
          "command": "create_offer_for_ids",
          "data": data
      }
      json_data = JSON.stringify(request);
      console.log(json_data)
      ws.send(json_data);

    } catch (e) {
        console.log("save failed")
        dialogs.alert("Offer failed. Reason: " + response["reason"], ok => {});
        save_offer.disabled = false;
        save_offer.innerHTML = "Save";
    }
});

function create_offer_for_ids_response(response) {
    /*
    Called when response is received for create_offer_for_ids request
    */
   status = response["success"]

   if (status == "true") {
       dialogs.alert("Offer successfully created.", ok => {});
   } else {
       dialogs.alert("Offer failed. Reason: " + response["reason"], ok => {});
   }
    save_offer.disabled = false;
    save_offer.innerHTML = "Save";
}

function respond_to_offer_response(response) {
    /*
    Called when response is received for create_offer_for_ids request
    */
   status = JSON.parse(response["success"]);
   if (status == "true") {
       dialogs.alert("Offer accepted successfully into the mempool.", ok => {});
   } else {
       dialogs.alert("Offer failed. Reason: " + response["reason"], ok => {});
   }
    accept_offer.disabled = false;
    accept_offer.innerHTML = "Accept";
    view_offer_parent.classList.add("hidden_area");
    drag_parent.classList.remove("hidden_area");
}
