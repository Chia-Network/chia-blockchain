import { service_wallet } from '../util/service_names';
import type Wallet from '../types/Wallet';
import createWallet from '../util/createWallet';

type IncomingState = {
  mnemonic: string[];
  public_key_fingerprints: number[];
  selected_fingerprint?: number | null;
  logged_in_received: boolean;
  logged_in: boolean;
  wallets: Wallet[];
  status: {
    connections: [];
    connection_count: number;
    syncing: boolean;
    height?: number;
  };
  send_transaction_result?: string | null;
  show_create_backup: boolean;
  server_started?: boolean;
};

const initialState: IncomingState = {
  mnemonic: [],
  public_key_fingerprints: [],
  selected_fingerprint: null,
  logged_in_received: false,
  logged_in: false,
  wallets: [],
  status: {
    connections: [],
    connection_count: 0,
    syncing: false,
  },
  show_create_backup: false,
};

export default function incomingReducer(
  state: IncomingState = { ...initialState },
  action: any,
): IncomingState {
  switch (action.type) {
    case 'SHOW_CREATE_BACKUP':
      return {
        ...state,
        show_create_backup: action.show,
      };
    case 'SELECT_FINGERPRINT':
      return {
        ...state,
        selected_fingerprint: action.fingerprint,
      };
    case 'UNSELECT_FINGERPRINT':
      return {
        ...state,
        selected_fingerprint: null,
      };
    case 'LOG_OUT':
      return {
        ...initialState,
        logged_in_received: true,
        public_key_fingerprints: state.public_key_fingerprints,
      };

    case 'CLEAR_SEND':
      var id = action.message.data.wallet_id;
      var wallet = state.wallets[Number.parseInt(id)];
      wallet.sending_transaction = false;
      wallet.send_transaction_result = null;
      return {
        ...state,
      };
    case 'OUTGOING_MESSAGE':
      if (
        action.message.command === 'send_transaction' ||
        action.message.command === 'cc_spend'
      ) {
        id = action.message.data.wallet_id;
        wallet = state.wallets[Number.parseInt(id)];
        wallet.sending_transaction = false;
        wallet.send_transaction_result = null;
        return {
          ...state,
        };
      }
      return state;
    case 'INCOMING_MESSAGE':
      if (action.message.origin !== service_wallet) {
        return state;
      }

      const { message } = action;
      const { data } = message;
      const { command } = message;
      let success;
      let wallets;
      if (command === 'generate_mnemonic') {
        const mnemonic =
          typeof message.data.mnemonic === 'string'
            ? message.data.mnemonic.split(' ')
            : message.data.mnemonic;

        return { ...state, mnemonic };
      }
      if (command === 'add_key') {
        success = data.success;
        return { ...state, logged_in: success };
      }
      if (command === 'log_in') {
        success = data.success;
        return { ...state, logged_in: success };
      }
      if (command === 'delete_all_keys') {
        success = data.success;
        if (success) {
          return {
            ...state,
            logged_in: false,
            public_key_fingerprints: [],
            logged_in_received: true,
          };
        }
      } else if (command === 'get_public_keys') {
        success = data.success;
        if (success) {
          const { public_key_fingerprints } = data;
          return {
            ...state,
            public_key_fingerprints,
            logged_in_received: true,
          };
        }
      } else if (command === 'ping') {
        const started = data.success;
        return { ...state, server_started: started };
      } else if (command === 'get_wallets') {
        if (data.success) {
          const { wallets } = data;
          const wallets_state = [];
          for (const object of wallets) {
            const walletid = Number(object.id);
            const wallet_obj = createWallet(
              walletid,
              object.name,
              object.type,
              object.data,
            );
            wallets_state[walletid] = wallet_obj;
          }
          return { ...state, wallets: wallets_state };
        }
      } else if (command === 'get_wallet_balance') {
        if (data.success) {
          const { wallet_balance } = data;
          id = wallet_balance.wallet_id;
          wallets = state.wallets;
          wallet = wallets[Number.parseInt(id)];
          if (!wallet) {
            return state;
          }
          const balance = wallet_balance.confirmed_wallet_balance;
          const unconfirmed_balance = wallet_balance.unconfirmed_wallet_balance;
          const pending_balance = unconfirmed_balance - balance;
          const { frozen_balance } = wallet_balance;
          const { spendable_balance } = wallet_balance;
          const change_balance = wallet_balance.pending_change;
          wallet.balance_total = balance;
          wallet.balance_pending = pending_balance;
          wallet.balance_frozen = frozen_balance;
          wallet.balance_spendable = spendable_balance;
          wallet.balance_change = change_balance;
          return { ...state };
        }
      } else if (command === 'get_transactions') {
        if (data.success) {
          id = data.wallet_id;
          const { transactions } = data;
          wallets = state.wallets;
          wallet = wallets[Number(id)];
          if (!wallet) {
            return state;
          }
          wallet.transactions = transactions.reverse();
          return { ...state };
        }
      } else if (command === 'get_next_address') {
        id = data.wallet_id;
        const { address } = data;
        wallets = state.wallets;
        wallet = wallets[Number(id)];
        if (!wallet) {
          return state;
        }
        wallet.address = address;
        return { ...state };
      } else if (command === 'get_connections') {
        if (data.success || data.connections) {
          return {
            ...state,
            status: {
              ...state.status,
              connections: data.connections,
              connection_count: data.connections.length,
            },
          };
        }
      } else if (command === 'get_height_info') {
        return {
          ...state,
          status: {
            ...state.status,
            height: data.height,
          },
        };
      } else if (command === 'get_sync_status') {
        if (data.success) {
          return {
            ...state,
            status: { ...state.status, syncing: data.syncing },
          };
        }
      } else if (command === 'cc_get_colour') {
        id = data.wallet_id;
        const { colour } = data;
        wallets = state.wallets;
        wallet = wallets[Number(id)];
        if (!wallet) {
          return state;
        }
        wallet.colour = colour;
        return { ...state };
      } else if (command === 'cc_get_name') {
        const id = data.wallet_id;
        const { name } = data;
        wallets = state.wallets;
        wallet = wallets[Number(id)];
        if (!wallet) {
          return state;
        }
        wallet.name = name;
        return { ...state };
      }
      if (command === 'state_changed' && data.state === 'tx_update') {
        const id = data.wallet_id;
        wallets = state.wallets;
        wallet = wallets[Number(id)];
        wallet.sending_transaction = false;
        wallet.send_transaction_result = message.data.additional_data;
        return { ...state };
      }
      return state;
    default:
      return state;
  }
}
