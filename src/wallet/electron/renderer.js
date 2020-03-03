//import { createRPC } from '@erebos/rpc-http-browser'
const jquery = require('jquery')
var QRCode = require('qrcode')
var canvas = document.getElementById('qr_canvas')
const Dialogs = require('dialogs')
const dialogs = Dialogs()

let send = document.querySelector('#send')
let new_address = document.querySelector('#new_address')
let copy = document.querySelector("#copy")
let receiver_address = document.querySelector("#receiver_puzzle_hash")
let amount = document.querySelector("#amount_to_send")
let table = document.querySelector("#tx_table").getElementsByTagName('tbody')[0]
let green_checkmark = "<i class=\"icon ion-md-checkmark-circle-outline green\"></i>"
let red_checkmark = "<i class=\"icon ion-md-close-circle-outline red\"></i>"
var myBalance = 0
var myUnconfirmedBalance = 0

send.addEventListener('click', () => {

    puzzlehash = receiver_address.value
    amount_value = amount.value
    data = {"puzzlehash": puzzlehash, "amount": amount_value}
    json_data = JSON.stringify(data)
    jquery.ajax({
        type: 'POST',
        url: 'http://127.0.0.1:9256/send_transaction',
        data: json_data,
        dataType: 'json'
    })
    .done(function(response) {
        console.log(response)
        success = response["success"]
        if (!success) {
            dialogs.alert("You don\'t have enough chia for this transactions", ok => {
            })
            return
        }
    })
    .fail(function(data) {
        console.log(data)
    });
})

new_address.addEventListener('click', () => {
    console.log("new address requesting")
    get_new_puzzlehash(0)
})

copy.addEventListener("click", () => {
    let puzzle_holder = document.querySelector("#puzzle_holder")
    puzzle_holder.select();
  /* Copy the text inside the text field */
    document.execCommand("copy");
})

function sleep(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function get_new_puzzlehash(timeout) {
    //wait for wallet.py to start up
    await sleep(timeout)
    jquery.ajax({
        type: 'POST',
        url: 'http://127.0.0.1:9256/get_next_puzzle_hash',
        dataType: 'json'
    })
    .done(function(response) {
        console.log(response)
        let puzzle_holder = document.querySelector("#puzzle_holder")
        puzzle_holder.value = response["puzzlehash"]
        QRCode.toCanvas(canvas, response["puzzlehash"], function (error) {
        if (error) console.error(error)
        console.log('success!');
        })
    })
    .fail(function(data) {
        console.log(data)
        get_new_puzzlehash(300)
    });
}

async function get_wallet_balance(timeout) {
    //wait for wallet.py to start up
    await sleep(timeout)
    jquery.ajax({
        type: 'POST',
        url: 'http://127.0.0.1:9256/get_wallet_balance',
        dataType: 'json'
    })
    .done(function(response) {
        console.log(response)
    })
    .fail(function(data) {
        console.log(data)
        get_wallet_balance(1000)
    });
}

async function get_transactions(timeout) {
    //wait for wallet.py to start up
    await sleep(timeout)
    jquery.ajax({
        type: 'POST',
        url: 'http://127.0.0.1:9256/get_transactions',
        dataType: 'json'
    })
    .done(function(response) {
        console.log(response)
        clean_table()

        for (var i = 0; i < response.txs.length; i++) {
            var tx = JSON.parse(response.txs[i]);
            console.log(tx);
            var row = table.insertRow(0);
            var cell_type = row.insertCell(0);
            var cell_to = row.insertCell(1);
            var cell_date = row.insertCell(2);
            var cell_status = row.insertCell(3);
            var cell_amount = row.insertCell(4);
            var cell_fee = row.insertCell(5);
            //type of transaction
            if (tx["incoming"]) {
                cell_type.innerHTML = "Incoming"
            } else {
                cell_type.innerHTML = "Outgoing"
            }
            // Receiving puzzle hash
            cell_to.innerHTML = tx["to_puzzle_hash"]

            // Date
            var date = new Date(parseInt(tx["created_at_time"]) * 1000);
            cell_date.innerHTML = "" + date

            // Confirmation status
            if (tx["confirmed"]) {
                 index = tx["confirmed_block_index"]
                 cell_status.innerHTML = "Confirmed" + green_checkmark +"</br>" + "Block: " + index;
            } else {
                 cell_status.innerHTML = "Pending " + red_checkmark;
            }

            // Amount and Fee
            cell_amount.innerHTML = tx["amount"];
            cell_fee.innerHTML = tx["fee_amount"]
        }

    })
    .fail(function(data) {
        console.log(data)
        get_transactions(1000)
    });
}

async function get_server_ready(timeout) {
    //wait for wallet.py to start up
    await sleep(timeout)
    jquery.ajax({
        type: 'POST',
        url: 'http://127.0.0.1:9256/get_server_ready',
        dataType: 'json'
    })
    .done(function(response) {
        console.log(response)
        success = response["success"]
        if (success) {
            get_transactions(0)
            get_new_puzzlehash(0)
            get_wallet_balance(0)
        }
    })
    .fail(function(data) {
        console.log(data)
        get_server_ready(100)
    });
}

function clean_table() {
    while (table.rows.length > 0) {
            table.deleteRow(0);
    }
}
clean_table()
get_server_ready(100)

