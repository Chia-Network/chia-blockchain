//import { createRPC } from '@erebos/rpc-http-browser'
const erebos = require('@erebos/rpc-http-browser')
const rpc = erebos.createRPC('http://localhost:9256')

let send = document.querySelector('#send')
let new_address = document.querySelector('#new_address')

send.addEventListener('click', () => {
    rpc.request('send', "").then(res => {
        console.log(res)
    })
})

new_address.addEventListener('click', () => {
  rpc.request('/get_next_puzzle_hash', "").then(res => {
    console.log(res)
  })
})

send.dispatchEvent(new Event('input'))
