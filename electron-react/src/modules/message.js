export const newMessage = msg => ({ type: 'OUTGOING_MESSAGE'});


export const format_message = (command, data) => {
  var action =  newMessage()
  action.command = command
  action.data = data
  return action
}

export const get_balance_for_wallet = (id) => {
  var action = newMessage()
  action.command = "get_wallet_balance"
  action.data = {"wallet_id": id}
  return action
}

export const send_transaction = (wallet_id, amount, fee, puzzle_hash) => {
  var action = newMessage()
  action.command = "send_transaction"
  action.data = {"wallet_id": wallet_id, "amount": amount, "fee": fee, "puzzle_hash": puzzle_hash}
  return action
}

export const genereate_mnemonics = () => {
  var action = newMessage()
  action.command = "generate_mnemonic"
  action.data = {}
  return action
}

export const log_in = (mnemonic) => {
  var action = newMessage()
  action.command = "log_in"
  action.data = {"mnemonic": mnemonic}
  return action
}

export const log_out = () => {
  var action = newMessage()
  action.command = "log_out"
  action.data = {}
  return action
}

export const get_transactions = (wallet_id) => {
  var action = newMessage()
  action.command = "get_transactions"
  action.data = {wallet_id: wallet_id}
  return action
}

export const get_puzzle_hash = (wallet_id) => {
  var action = newMessage()
  action.command = "get_next_puzzle_hash"
  action.data = {wallet_id: wallet_id}
  return action
}

export const farm_block = (puzzle_hash) => {
  var action = newMessage()
  action.command = "farm_block"
  action.data = {puzzle_hash: puzzle_hash}
  return action
}

export const get_height_info = () => {
  var action = newMessage()
  action.command = "get_height_info"
  action.data = {}
  return action
}

export const get_sync_status = () => {
  var action = newMessage()
  action.command = "get_sync_status"
  action.data = {}
  return action
}

export const get_connection_info = () => {
  var action = newMessage()
  action.command = "get_connection_info"
  action.data = {}
  return action
}

export const create_coloured_coin = (amount) => {
  var action = newMessage()
  action.command = "create_new_wallet"
  action.data = {
    wallet_type: "cc_wallet",
    mode: "new",
    amount: amount
  }
  return action
}

export const create_cc_for_colour = (colour) => {
  var action = newMessage()
  action.command = "create_new_wallet"
  action.data = {
    wallet_type: "cc_wallet",
    mode: "existing",
    colour: colour
  }
  return action
}

export const get_colour_info = (wallet_id) => {
  var action = newMessage()
  action.command = "cc_get_colour"
  action.data = {wallet_id: wallet_id}
  return action
}

export const get_colour_name = (wallet_id) => {
  var action = newMessage()
  action.command = "cc_get_name"
  action.data = {wallet_id: wallet_id}
  return action
}

export const rename_cc_wallet = (wallet_id, name) => {
  var action = newMessage()
  action.command = "cc_set_name"
  action.data = {wallet_id: wallet_id, name: name}
  return action
}

export const cc_spend = (wallet_id, puzzle_hash, amount) => {
  var action = newMessage()
  action.command = "cc_spend"
  action.data = {wallet_id: wallet_id, innerpuzhash: puzzle_hash, amount: amount,}
  return action
}

export const incomingMessage = (command, data) => ({ type: 'INCOMING_MESSAGE', command, data});

