export const newMessage = msg => ({ type: 'OUTGOING_MESSAGE'});


export const format_message = (command, data) => {
  var action =  newMessage()
  action.command = command
  action.data = data
  return action
}

export const get_balance_for_wallet = (wallet_id) => {
  var action = newMessage()
  action.command = "get_wallet_balance"
  action.data = {"wallet_id": wallet_id}
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
  action.data = {"data": "dummy"}
  return action
}

export const log_in = (mnemonic) => {
  var action = newMessage()
  action.command = "log_in"
  action.data = {"mnemonic": mnemonic}
  return action
}

export const incomingMessage = msg => ({ type: 'INCOMING_MESSAGE'});


export const mnemonic_received = (data) => {
  var action = incomingMessage()
  action.command = "generate_mnemonic"
  action.data = data
  return action
}
