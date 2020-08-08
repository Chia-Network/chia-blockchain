import { service_wallet } from "../util/service_names";
import { DEFAULT_ECDH_CURVE } from "tls";

export const Wallet = (id, name, type, data) => ({
  id: id,
  name: name,
  type: type,
  data: data,
  balance_total: 0,
  balance_pending: 0,
  balance_spendable: 0,
  balance_frozen: 0,
  balance_change: 0,
  transactions: [],
  puzzle_hash: "",
  colour: "",
  send_transaction_result: ""
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

// export const initial_wallet = Wallet(0, "Chia Wallet", "STANDARD_WALLET", "");

const initial_state = {
  mnemonic: [],
  public_key_fingerprints: [],
  selected_fingerprint: null,
  logged_in_received: false,
  logged_in: false,
  wallets: [],
  status: {
    connections: [],
    connection_count: 0,
    syncing: false
  },
  sending_transaction: false,
  show_create_backup: false
};

export const incomingReducer = (state = { ...initial_state }, action) => {
  switch (action.type) {
    case "SHOW_CREATE_BACKUP":
      return {
        ...state,
        show_create_backup: action.show
      };
    case "SELECT_FINGERPRINT":
      return {
        ...state,
        selected_fingerprint: action.fingerprint
      };
    case "UNSELECT_FINGERPRINT":
      return {
        ...state,
        selected_fingerprint: null
      };
    case "LOG_OUT":
      return {
        ...initial_state,
        logged_in_received: true,
        public_key_fingerprints: state.public_key_fingerprints
      };

    case "CLEAR_SEND":
      state["sending_transaction"] = false;
      state["send_transaction_result"] = null;
      return state;

    case "OUTGOING_MESSAGE":
      if (
        action.message.command === "send_transaction" ||
        action.message.command === "cc_spend"
      ) {
        state["sending_transaction"] = true;
        state["send_transaction_result"] = null;
      }
      return state;
    case "INCOMING_MESSAGE":
      if (action.message.origin !== service_wallet) {
        return state;
      }

      const message = action.message;
      const data = message.data;
      const command = message.command;
      let success, id, wallet, wallets;
      if (command === "generate_mnemonic") {
        var mnemonic_data = message.data.mnemonic;
        return { ...state, mnemonic: mnemonic_data.split(" ") };
      } else if (command === "add_key") {
        success = data.success;
        return { ...state, logged_in: success };
      } else if (command === "log_in") {
        success = data.success;
        return { ...state, logged_in: success };
      } else if (command === "delete_all_keys") {
        success = data.success;
        if (success) {
          return {
            ...state,
            logged_in: false,
            public_key_fingerprints: [],
            logged_in_received: true
          };
        }
      } else if (command === "get_public_keys") {
        success = data.success;
        if (success) {
          var public_key_fingerprints = data.public_key_fingerprints;
          return {
            ...state,
            public_key_fingerprints: public_key_fingerprints,
            logged_in_received: true
          };
        }
      } else if (command === "ping") {
        var started = data.success;
        return { ...state, server_started: started };
      } else if (command === "get_wallets") {
        if (data.success) {
          const wallets = data.wallets;
<<<<<<< HEAD
          console.log(wallets);
=======
>>>>>>> fixed rl interval limit setup; style and text edits; cleanup
          var wallets_state = [];
          for (let object of wallets) {
            id = parseInt(object.id);
            var wallet_obj = Wallet(id, object.name, object.type, object.data);
            wallets_state[id] = wallet_obj;
          }
          // console.log(wallets_state);
          return { ...state, wallets: wallets_state };
        }
      } else if (command === "get_wallet_balance") {
        if (data.success) {
          const wallet_balance = data.wallet_balance;
          id = wallet_balance.wallet_id;
          wallets = state.wallets;
          wallet = wallets[parseInt(id)];
          if (!wallet) {
            return state;
          }
          var balance = wallet_balance.confirmed_wallet_balance;
          var unconfirmed_balance = wallet_balance.unconfirmed_wallet_balance;
          var pending_balance = unconfirmed_balance - balance;
          var frozen_balance = wallet_balance.frozen_balance;
          var spendable_balance = wallet_balance.spendable_balance;
          var change_balance = wallet_balance.pending_change;
          wallet.balance_total = balance;
          wallet.balance_pending = pending_balance;
          wallet.balance_frozen = frozen_balance;
          wallet.balance_spendable = spendable_balance;
          wallet.balance_change = change_balance;
          return state;
        }
      } else if (command === "get_transactions") {
        if (data.success) {
          id = data.wallet_id;
          var transactions = data.txs;
          wallets = state.wallets;
          wallet = wallets[parseInt(id)];
          if (!wallet) {
            return state;
          }
          wallet.transactions = transactions.reverse();
          return state;
        }
      } else if (command === "get_next_puzzle_hash") {
        id = data.wallet_id;
        var puzzle_hash = data.puzzle_hash;
        wallets = state.wallets;
        wallet = wallets[parseInt(id)];
        if (!wallet) {
          return state;
        }
        wallet.puzzle_hash = puzzle_hash;
        return { ...state };
      } else if (command === "get_connections") {
        if (data.success || data.connections) {
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
        if (data.success) {
          const syncing = data.syncing;
          state.status["syncing"] = syncing;
          return state;
        }
      } else if (command === "cc_get_colour") {
        id = data.wallet_id;
        const colour = data.colour;
        wallets = state.wallets;
        wallet = wallets[parseInt(id)];
        if (!wallet) {
          return state;
        }
        wallet.colour = colour;
        return state;
      } else if (command === "cc_get_name") {
        const id = data.wallet_id;
        const name = data.name;
        wallets = state.wallets;
        wallet = wallets[parseInt(id)];
        if (!wallet) {
          return state;
        }
        wallet.name = name;
        return state;
      }
      if (command === "send_transaction" || command === "cc_spend") {
        state["sending_transaction"] = false;
        const id = data.id;
        const name = data.name;
        wallets = state.wallets;
        wallet = wallets[parseInt(id)];
        wallet.send_transaction_result = message.data;
        return state;
      } else if (command === "rl_set_user_info") {
        const success = data;
<<<<<<< HEAD
        console.log("RL SET USER INFO SUCCESS: ", success);
      } else if (command === "create_new_wallet") {
        const success = data;
        console.log("RL CREATE WALLET SUCCESS: ", success);
=======
        console.log("RL SET USER INFO SUCCESS: ", success)
      }
      else if (command === "create_new_wallet") {
        const success = data["success"];
>>>>>>> fixed rl interval limit setup; style and text edits; cleanup
      }
      return state;
    default:
      return state;
  }
};
