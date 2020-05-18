import { service_wallet_server } from "../util/service_names";

export const walletMessage = () => ({
  type: "OUTGOING_MESSAGE",
  destination: service_wallet_server
});

export const format_message = (command, data) => {
  var action = walletMessage();
  action.command = command;
  action.data = data;
  return action;
};

export const pingWallet = () => {
  var action = walletMessage();
  action.command = "ping";
  action.data = {};
  return action;
};

export const get_balance_for_wallet = id => {
  var action = walletMessage();
  action.command = "get_wallet_balance";
  action.data = { wallet_id: id };
  return action;
};

export const send_transaction = (wallet_id, amount, fee, puzzle_hash) => {
  var action = walletMessage();
  action.command = "send_transaction";
  action.data = {
    wallet_id: wallet_id,
    amount: amount,
    fee: fee,
    puzzle_hash: puzzle_hash
  };
  return action;
};

export const genereate_mnemonics = () => {
  var action = walletMessage();
  action.command = "generate_mnemonic";
  action.data = {};
  return action;
};

export const add_key = mnemonic => {
  var action = walletMessage();
  action.command = "add_key";
  action.data = { mnemonic: mnemonic };
  return action;
};

export const delete_key = fingerprint => {
  var action = walletMessage();
  action.command = "delete_key";
  action.data = { fingerprint: fingerprint };
  return action;
};

export const delete_all_keys = () => {
  var action = walletMessage();
  action.command = "delete_all_keys";
  action.data = {};
  return action;
};

export const log_in = fingerprint => {
  var action = walletMessage();
  action.command = "log_in";
  action.data = { fingerprint: fingerprint };
  return action;
};

export const get_transactions = wallet_id => {
  var action = walletMessage();
  action.command = "get_transactions";
  action.data = { wallet_id: wallet_id };
  return action;
};

export const get_puzzle_hash = wallet_id => {
  var action = walletMessage();
  action.command = "get_next_puzzle_hash";
  action.data = { wallet_id: wallet_id };
  return action;
};

export const farm_block = puzzle_hash => {
  var action = walletMessage();
  action.command = "farm_block";
  action.data = { puzzle_hash: puzzle_hash };
  return action;
};

export const get_height_info = () => {
  var action = walletMessage();
  action.command = "get_height_info";
  action.data = {};
  return action;
};

export const get_sync_status = () => {
  var action = walletMessage();
  action.command = "get_sync_status";
  action.data = {};
  return action;
};

export const get_connection_info = () => {
  var action = walletMessage();
  action.command = "get_connection_info";
  action.data = {};
  return action;
};

export const create_coloured_coin = amount => {
  var action = walletMessage();
  action.command = "create_new_wallet";
  action.data = {
    wallet_type: "cc_wallet",
    mode: "new",
    amount: amount
  };
  return action;
};

export const create_cc_for_colour = colour => {
  var action = walletMessage();
  action.command = "create_new_wallet";
  action.data = {
    wallet_type: "cc_wallet",
    mode: "existing",
    colour: colour
  };
  return action;
};

export const get_colour_info = wallet_id => {
  var action = walletMessage();
  action.command = "cc_get_colour";
  action.data = { wallet_id: wallet_id };
  return action;
};

export const get_colour_name = wallet_id => {
  var action = walletMessage();
  action.command = "cc_get_name";
  action.data = { wallet_id: wallet_id };
  return action;
};

export const rename_cc_wallet = (wallet_id, name) => {
  var action = walletMessage();
  action.command = "cc_set_name";
  action.data = { wallet_id: wallet_id, name: name };
  return action;
};

export const cc_spend = (wallet_id, puzzle_hash, amount) => {
  var action = walletMessage();
  action.command = "cc_spend";
  action.data = {
    wallet_id: wallet_id,
    innerpuzhash: puzzle_hash,
    amount: amount
  };
  return action;
};

export const create_trade_offer = (trades, filepath) => {
  var action = walletMessage();
  action.command = "create_offer_for_ids";
  const data = {
    ids: trades,
    filename: filepath
  };
  action.data = data;
  return action;
};

export const logOut = (command, data) => ({ type: "LOG_OUT", command, data });

export const parse_trade_offer = filepath => {
  var action = walletMessage();
  action.command = "get_discrepancies_for_offer";
  const data = { filename: filepath };
  action.data = data;
  return action;
};

export const accept_trade_offer = filepath => {
  var action = walletMessage();
  action.command = "respond_to_offer";
  action.data = { filename: filepath };
  return action;
};

export const incomingMessage = message => ({
  type: "INCOMING_MESSAGE",
  message: message
});
