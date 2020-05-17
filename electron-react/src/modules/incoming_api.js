import {
  service_wallet_server,
  service_full_node
} from "../util/service_names";

export const Wallet = (id, name, type, data) => ({
  id: id,
  name: name,
  type: type,
  data: data,
  balance_total: 0,
  balance_pending: 0,
  transactions: [],
  puzzle_hash: "",
  colour: ""
});

export const Transaction = (
  confirmed_at_index,
  created_at_time,
  to_puzzle_hash,
  amount,
  fee_amount,
  incoming,
  confirmed,
  sent,
  spend_bundle,
  additions,
  removals,
  wallet_id
) => ({
  confirmed_at_index: confirmed_at_index,
  created_at_time: created_at_time,
  to_puzzle_hash: to_puzzle_hash,
  amount: amount,
  fee_amount: fee_amount,
  incoming: incoming,
  confirmed: confirmed,
  sent: sent,
  spend_bundle: spend_bundle,
  additions: additions,
  removals: removals,
  wallet_id: wallet_id
});

export const initial_wallet = Wallet(1, "Chia Wallet", "STANDARD_WALLET", "");

const initial_state = {
  mnemonic: [],
  public_key_fingerprints: [],
  logged_in_received: false,
  logged_in: false,
  wallets: [, initial_wallet],
  status: {
    connections: [],
    connection_count: 0,
    syncing: false
  }
};

export const incomingReducer = (state = { ...initial_state }, action) => {
  switch (action.type) {
    case "LOG_OUT":
      if (action.message.command === "log_out") {
        return { ...state, logged_in: false };
      }
    case "INCOMING_MESSAGE":
      if (action.message.origin !== service_wallet_server) {
        return state;
      }

      const message = action.message;
      const data = message.data;
      const command = message.command;
      if (command === "generate_mnemonic") {
        var mnemonic_data = message.data.mnemonic;
        return { ...state, mnemonic: mnemonic_data };
      } else if (command === "add_key") {
        var success = data.success;
        return { ...state, logged_in: success };
      } else if (command === "log_in") {
        var success = data.success;
        return { ...state, logged_in: success };
      } else if (command === "delete_all_keys") {
        var success = data.success;
        if (success) {
          return {
            ...state,
            logged_in: false,
            public_key_fingerprints: [],
            logged_in_received: true
          };
        }
      } else if (command === "get_public_keys") {
        var public_key_fingerprints = data.public_key_fingerprints;
        return {
          ...state,
          public_key_fingerprints: public_key_fingerprints,
          logged_in_received: true
        };
      } else if (command === "logged_in") {
        var logged_in = data.logged_in;
        return { ...state, logged_in: logged_in, logged_in_received: true };
      } else if (command === "ping") {
        var started = data.success;
        return { ...state, server_started: started };
      } else if (command === "get_wallets") {
        if (data.success) {
          const wallets = data.wallets;
          var wallets_state = [];
          wallets.map(object => {
            var id = parseInt(object.id);
            var wallet_obj = Wallet(id, object.name, object.type, object.data);
            wallets_state[id] = wallet_obj;
          });
          console.log(wallets_state);
          return { ...state, wallets: wallets_state };
        }
      } else if (command === "get_wallet_balance") {
        if (data.success) {
          var id = data.wallet_id;
          var wallets = state.wallets;
          var wallet = wallets[parseInt(id)];
          wallet.balance = balance;
          var balance = data.confirmed_wallet_balance;
          console.log("balance is: " + balance);
          var unconfirmed_balance = data.unconfirmed_wallet_balance;
          wallet.balance_total = balance;
          wallet.balance_pending = unconfirmed_balance;
          return state;
        }
      } else if (command === "get_transactions") {
        if (data.success) {
          var id = data.wallet_id;
          var transactions = data.txs;
          var wallets = state.wallets;
          var wallet = wallets[parseInt(id)];
          wallet.transactions = transactions.reverse();
          return state;
        }
      } else if (command === "get_next_puzzle_hash") {
        var id = data.wallet_id;
        var puzzle_hash = data.puzzle_hash;
        var wallets = state.wallets;
        var wallet = wallets[parseInt(id)];
        console.log("wallet_id here: " + id);
        wallet.puzzle_hash = puzzle_hash;
        return { ...state };
      } else if (command == "get_connection_info") {
        if (data.success) {
          const connections = data.connections;
          state.status["connections"] = connections;
          state.status["connection_count"] = connections.length;
          return state;
        }
      } else if (command === "get_height_info") {
        const height = data.height;
        state.status["height"] = height;
        return { ...state };
      } else if (command === "get_sync_status") {
        console.log("command get_sync_status");
        if (data.success) {
          const syncing = data.syncing;
          state.status["syncing"] = syncing;
          return state;
        }
      } else if (command === "cc_get_colour") {
        const id = data.wallet_id;
        const colour = data.colour;
        var wallets = state.wallets;
        var wallet = wallets[parseInt(id)];
        wallet.colour = colour;
        return state;
      } else if (command === "cc_get_name") {
        const id = data.wallet_id;
        const name = data.name;
        var wallets = state.wallets;
        var wallet = wallets[parseInt(id)];
        wallet.name = name;
        return state;
      }
      return state;
    default:
      return state;
  }
};
