export const newMessage = msg => ({ type: 'NEW_MESSAGE'});


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