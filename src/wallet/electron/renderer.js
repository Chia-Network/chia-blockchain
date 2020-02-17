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

var myBalance = 0
var myUnconfirmedBalance = 0

send.addEventListener('click', () => {
    if (myUnconfirmedBalance == 0) {
        dialogs.alert("You don\'t have enough chia for this transactions", ok => {

        })
        return
    }
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

get_new_puzzlehash(300)

