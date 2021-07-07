import { service_wallet } from '../util/service_names';
import {
  async_api,
  pwStatusMessage,
  getWalletsMessage,
  get_balance_for_wallet,
  getTransactionMessage,
  deleteUnconfirmedTransactionsMessage,
} from './message';
import type WalletBalance from '../types/WalletBalance';
import type Wallet from '../types/Wallet';
import type Transaction from '../types/Transaction';
import type PoolWalletStatus from '../types/PoolWalletStatus';
import mergeArrayItem from '../util/mergeArrayItem';
import mergeArrays from '../util/mergeArrays';

export function getTransaction(transactionId: string) {
  return async (dispatch): Promise<Transaction> => {
    const { data } = await async_api(
      dispatch,
      getTransactionMessage(transactionId),
      false,
    );

    return data?.transaction;
  };
}

export function getPwStatus(walletId: number) {
  return async (dispatch): Promise<PoolWalletStatus> => {
    const { data } = await async_api(
      dispatch,
      pwStatusMessage(walletId),
      false,
      true,
    );

    return {
      wallet_id: walletId,
      ...data?.state,
    };
  };
}

export function getWallets() {
  return async (dispatch): Promise<Wallet[]> => {
    const { data } = await async_api(
      dispatch,
      getWalletsMessage(),
      false,
      true,
    );

    return data?.wallets;
  };
}

export function getWalletBalance(walletId: number) {
  return async (dispatch): Promise<WalletBalance> => {
    const { data } = await async_api(
      dispatch,
      get_balance_for_wallet(walletId),
      false,
      true,
    );

    return data?.wallet_balance;
  };
}

export function deleteUnconfirmedTransactions(walletId: number) {
  return async (dispatch): Promise<void> => {
    await async_api(
      dispatch,
      deleteUnconfirmedTransactionsMessage(walletId),
      false,
    );
  };
}

export type IncomingState = {
  mnemonic: string[];
  public_key_fingerprints: number[];
  selected_fingerprint?: number | null;
  logged_in_received: boolean;
  logged_in: boolean;
  wallets?: Wallet[];
  status: {
    connections: [];
    connection_count: number;
    syncing: boolean;
    synced: boolean;
    height?: number;
  };
  send_transaction_result?: string | null;
  show_create_backup: boolean;
  server_started?: boolean;
  network_info?: {
    network_name: string;
    network_prefix: string;
  };
  farmed_amount?: {
    farmed_amount: number;
    pool_reward_amount: number;
    farmer_reward_amount: number;
    fee_amount: number;
    last_height_farmed: number;
  };
  reward_targets?: {
    farmer_target?: string;
    pool_target?: string;
  };
};

const initialState: IncomingState = {
  mnemonic: [],
  public_key_fingerprints: [],
  selected_fingerprint: null,
  logged_in_received: false,
  logged_in: false,
  status: {
    connections: [],
    connection_count: 0,
    syncing: false,
    synced: false,
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
      const wallet_id = action.message.data.wallet_id;
      const { wallets, ...rest } = state;

      return {
        ...rest,
        wallets: mergeArrayItem(
          wallets,
          (wallet: Wallet) => wallet.id === wallet_id,
          {
            sending_transaction: false,
            send_transaction_result: null,
          },
        ),
      };
    case 'OUTGOING_MESSAGE':
      if (
        action.message.command === 'send_transaction' ||
        action.message.command === 'cc_spend'
      ) {
        const wallet_id = action.message.data.wallet_id;
        const { wallets, ...rest } = state;

        return {
          ...rest,
          wallets: mergeArrayItem(
            wallets,
            (wallet: Wallet) => wallet.id === wallet_id,
            {
              sending_transaction: false,
              send_transaction_result: null,
            },
          ),
        };
      }
      return state;
    case 'INCOMING_MESSAGE':
      if (action.message.origin !== service_wallet) {
        return state;
      }

      const {
        message,
        message: {
          data,
          command,
          data: { success },
        },
      } = action;

      if (command === 'generate_mnemonic') {
        const mnemonic =
          typeof message.data.mnemonic === 'string'
            ? message.data.mnemonic.split(' ')
            : message.data.mnemonic;

        return {
          ...state,
          mnemonic,
        };
      }
      if (command === 'add_key') {
        return {
          ...state,
          logged_in: success,
          selected_fingerprint: success ? data.fingerprint : undefined,
        };
      }
      if (command === 'log_in') {
        return {
          ...state,
          logged_in: success,
        };
      }
      if (command === 'delete_all_keys' && success) {
        return {
          ...state,
          logged_in: false,
          selected_fingerprint: undefined,
          public_key_fingerprints: [],
          logged_in_received: true,
        };
      } else if (command === 'get_public_keys' && success) {
        const { public_key_fingerprints } = data;

        return {
          ...state,
          public_key_fingerprints,
          logged_in_received: true,
        };
      } else if (command === 'ping') {
        return {
          ...state,
          server_started: success,
        };
      } else if (command === 'get_wallets' && success) {
        const { wallets } = data;

        return {
          ...state,
          wallets: mergeArrays(state.wallets, (wallet) => wallet.id, wallets),
        };
      } else if (command === 'get_wallet_balance' && success) {
        const { wallets, ...rest } = state;

        const {
          wallet_balance,
          wallet_balance: {
            wallet_id,
            confirmed_wallet_balance,
            unconfirmed_wallet_balance,
          },
        } = data;

        const pending_balance =
          unconfirmed_wallet_balance - confirmed_wallet_balance;

        return {
          ...rest,
          wallets: mergeArrayItem(
            wallets,
            (wallet: Wallet) => wallet.id === wallet_id,
            {
              wallet_balance: {
                ...wallet_balance,
                pending_balance,
              },
            },
          ),
        };
      } else if (command === 'get_transactions' && success) {
        const { wallet_id, transactions } = data;
        const { wallets, ...rest } = state;

        return {
          ...rest,
          wallets: mergeArrayItem(
            wallets,
            (wallet: Wallet) => wallet.id === wallet_id,
            {
              transactions: transactions.reverse(),
            },
          ),
        };
      } else if (command === 'get_next_address' && success) {
        const { wallet_id, address } = data;
        const { wallets, ...rest } = state;

        return {
          ...rest,
          wallets: mergeArrayItem(
            wallets,
            (wallet: Wallet) => wallet.id === wallet_id,
            {
              address,
            },
          ),
        };
      } else if (command === 'get_connections' && success) {
        if (data.connections) {
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
      } else if (command === 'get_network_info' && success) {
        return {
          ...state,
          network_info: {
            network_name: data.network_name,
            network_prefix: data.network_prefix,
          },
        };
      } else if (command === 'get_sync_status' && success) {
        return {
          ...state,
          status: {
            ...state.status,
            syncing: data.syncing,
            synced: data.synced,
          },
        };
      } else if (command === 'cc_get_colour') {
        const { wallet_id, colour } = data;
        const { wallets, ...rest } = state;

        return {
          ...rest,
          wallets: mergeArrayItem(
            wallets,
            (wallet: Wallet) => wallet.id === wallet_id,
            {
              colour,
            },
          ),
        };
      } else if (command === 'cc_get_name') {
        const { wallet_id, name } = data;
        const { wallets, ...rest } = state;

        return {
          ...rest,
          wallets: mergeArrayItem(
            wallets,
            (wallet: Wallet) => wallet.id === wallet_id,
            {
              name,
            },
          ),
        };
      } else if (command === 'did_get_did') {
        const { wallet_id, my_did: mydid, coin_id: didcoin } = data;
        const { wallets, ...rest } = state;

        return {
          ...rest,
          wallets: mergeArrayItem(
            wallets,
            (wallet: Wallet) => wallet.id === wallet_id,
            {
              mydid,
              didcoin,
            },
          ),
        };
      } else if (command === 'did_get_recovery_list') {
        const {
          wallet_id,
          recover_list: backup_dids,
          num_required: dids_num_req,
        } = data;
        const { wallets, ...rest } = state;

        return {
          ...rest,
          wallets: mergeArrayItem(
            wallets,
            (wallet: Wallet) => wallet.id === wallet_id,
            {
              backup_dids,
              dids_num_req,
            },
          ),
        };
      } else if (command === 'did_create_attest') {
        const { wallet_id, message_spend_bundle: did_attest } = data;
        const { wallets, ...rest } = state;

        return {
          ...rest,
          wallets: mergeArrayItem(
            wallets,
            (wallet: Wallet) => wallet.id === wallet_id,
            {
              did_attest,
            },
          ),
        };
      }

      if (command === 'state_changed' && data.state === 'tx_update') {
        const { wallet_id, additional_data: send_transaction_result } = data;
        const { wallets, ...rest } = state;

        return {
          ...rest,
          wallets: mergeArrayItem(
            wallets,
            (wallet: Wallet) => wallet.id === wallet_id,
            {
              sending_transaction: false,
              send_transaction_result,
            },
          ),
        };
      }
      if (command === 'get_farmed_amount') {
        return { ...state, farmed_amount: data };
      }
      if (command === 'get_reward_targets') {
        return { ...state, reward_targets: data };
      }
      return state;
    default:
      return state;
  }
}
