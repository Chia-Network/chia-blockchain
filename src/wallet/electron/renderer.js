//import { createRPC } from '@erebos/rpc-http-browser'
const jquery = require('jquery')
var QRCode = require('qrcode')
var canvas = document.getElementById('qr_canvas')

let send = document.querySelector('#send')
let new_address = document.querySelector('#new_address')
let copy = document.querySelector("#copy")

send.addEventListener('click', () => {

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
    // Make sure that the formMessages div has the 'success' class.
        console.log(response)
        let puzzle_holder = document.querySelector("#puzzle_holder")
        puzzle_holder.value = response["puzzlehash"]
        QRCode.toCanvas(canvas, response["puzzlehash"], function (error) {
        if (error) console.error(error)
        console.log('success!');
        })
    })
    .fail(function(data) {
        // Make sure that the formMessages div has the 'error' class.
        console.log(data)

        get_new_puzzlehash(300)
    });
}

get_new_puzzlehash(300)

