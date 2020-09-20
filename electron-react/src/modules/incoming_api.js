import { service_wallet } from "../util/service_names";

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
  address: "",
  colour: "",
  sending_transaction: false,
  send_transaction_result: ""
});

export const Transaction = (
  confirmed_at_index,
  created_at_time,
  to_address,
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
  to_address: to_address,
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
      var id = action.message.data.wallet_id;
      var wallet = state.wallets[parseInt(id)];
      wallet.sending_transaction = false;
      wallet.send_transaction_result = null;
      return {
        ...state
      };
    case "OUTGOING_MESSAGE":
      if (
        action.message.command === "send_transaction" ||
        action.message.command === "cc_spend"
      ) {
        id = action.message.data.wallet_id;
        wallet = state.wallets[parseInt(id)];
        wallet.sending_transaction = false;
        wallet.send_transaction_result = null;
        return {
          ...state
        };
      }
      return state;
    case "INCOMING_MESSAGE":
      if (action.message.origin !== service_wallet) {
        return state;
      }

      const message = action.message;
      const data = message.data;
      const command = message.command;
      let success, wallets;
      if (command === "generate_mnemonic") {
        return { ...state, mnemonic: message.data.mnemonic };
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
          var wallets_state = [];
          for (let object of wallets) {
            var walletid = parseInt(object.id);
            var wallet_obj = Wallet(
              walletid,
              object.name,
              object.type,
              object.data
            );
            wallets_state[walletid] = wallet_obj;
          }
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
          return { ...state };
        }
      } else if (command === "get_transactions") {
        if (data.success) {
          id = data.wallet_id;
          var transactions = data.transactions;
          wallets = state.wallets;
          wallet = wallets[parseInt(id)];
          if (!wallet) {
            return state;
          }
          wallet.transactions = transactions.reverse();
          return { ...state };
        }
      } else if (command === "get_next_address") {
        id = data.wallet_id;
        var address = data.address;
        wallets = state.wallets;
        wallet = wallets[parseInt(id)];
        if (!wallet) {
          return state;
        }
        wallet.address = address;
        return { ...state };
      } else if (command === "get_connections") {
        if (data.success || data.connections) {
          return {
            ...state,
            status: {
              ...state.status,
              connections: data.connections,
              connection_count: data.connections.length
            }
          };
        }
      } else if (command === "get_height_info") {
        return { ...state, status: { ...state.status, height: data.height } };
      } else if (command === "get_sync_status") {
        if (data.success) {
          return {
            ...state,
            status: { ...state.status, syncing: data.syncing }
          };
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
        return { ...state };
      } else if (command === "cc_get_name") {
        const id = data.wallet_id;
        const name = data.name;
        wallets = state.wallets;
        wallet = wallets[parseInt(id)];
        if (!wallet) {
          return state;
        }
        wallet.name = name;
        return { ...state };
      }
      if (command === "state_changed" && data.state === "tx_update") {
        const id = data.wallet_id;
        wallets = state.wallets;
        wallet = wallets[parseInt(id)];
        wallet.sending_transaction = false;
        wallet.send_transaction_result = message.data.additional_data;
        return { ...state };
      }
      return state;
    default:
      return state;
  }
};
