import { push } from 'connected-react-router';
import { service_wallet } from '../util/service_names';
import { openProgress, closeProgress } from './progress';
import { refreshAllState } from '../middleware/middleware_api';
import { setIncorrectWord, resetMnemonic } from './mnemonic';
import { openErrorDialog } from './dialog';
import { createState, changeCreateWallet, ALL_OPTIONS } from './createWallet';
import {
  addPlotDirectory,
  getPlotDirectories,
  removePlotDirectory,
  getPlots,
  refreshPlots,
} from './harvesterMessages';
import {
  setBackupInfo,
  changeBackupView,
  presentBackupInfo,
  selectFilePath,
} from './backup';
import { exitDaemon } from './daemon_messages';
import { wsDisconnect } from './websocket';
import config from '../config/config';

const { backup_host } = config;

// TODO this is not doing anything because wallet id is missing
export const clearSend = () => {
  const action = {
    type: 'CLEAR_SEND',
    mesasge: '',
  };
  return action;
};

export const walletMessage = (message) => ({
  type: 'OUTGOING_MESSAGE',
  message: {
    destination: service_wallet,
    ...message,
  },
});

export const selectFingerprint = (fingerprint) => ({
  type: 'SELECT_FINGERPRINT',
  fingerprint,
});

export const unselectFingerprint = () => ({
  type: 'UNSELECT_FINGERPRINT',
});

export const selectMnemonic = (mnemonic) => ({
  type: 'SELECT_MNEMONIC',
  mnemonic,
});

export const showCreateBackup = (show) => ({
  type: 'SHOW_CREATE_BACKUP',
  show,
});

export const async_api = (dispatch, action, openSpinner, usePromiseReject) => {
  if (openSpinner) {
    dispatch(openProgress());
  }

  const promise = new Promise((resolve, reject) => {
    action.resolve = resolve;
    action.reject = reject;
  }).finally(() => {
    dispatch(closeProgress());
  });

  action.usePromiseReject = usePromiseReject;

  dispatch(action);

  return promise;
};

export const format_message = (command, data) => {
  const action = walletMessage();
  action.message.command = command;
  action.message.data = data;
  return action;
};

export const pingWallet = () => {
  const action = walletMessage();
  action.message.command = 'ping';
  action.message.data = {};
  return action;
};

export const get_balance_for_wallet = (id) => {
  const action = walletMessage();
  action.message.command = 'get_wallet_balance';
  action.message.data = { wallet_id: id };
  return action;
};

export const get_farmed_amount = () => {
  const action = walletMessage();
  action.message.command = 'get_farmed_amount';
  action.message.data = {};
  return action;
};

export const send_transaction = (wallet_id, amount, fee, address) => {
  const action = walletMessage();
  action.message.command = 'send_transaction';
  action.message.data = {
    wallet_id,
    amount,
    fee,
    address,
  };
  return action;
};

export const genereate_mnemonics = () => {
  const action = walletMessage();
  action.message.command = 'generate_mnemonic';
  action.message.data = {};
  return action;
};

export const add_key = (mnemonic, type, file_path) => {
  const action = walletMessage();
  action.message.command = 'add_key';
  action.message.data = {
    mnemonic,
    type,
    file_path,
  };
  return action;
};

export const add_new_key_action = (mnemonic) => (dispatch) =>
  async_api(dispatch, add_key(mnemonic, 'new_wallet', null), true).then(
    (response) => {
      if (response.data.success) {
        // Go to wallet
        dispatch(resetMnemonic());
        dispatch(format_message('get_public_keys', {}));
        dispatch(refreshAllState());
        dispatch(push('/dashboard'));
      } else {
        if (response.data.word) {
          dispatch(setIncorrectWord(response.data.word));
          dispatch(push('/wallet/import'));
        } else if (response.data.error === 'Invalid order of mnemonic words') {
          dispatch(push('/wallet/import'));
        }
        const { error } = response.data;
        dispatch(openErrorDialog(error));
      }
    },
  );

export const add_and_skip_backup = (mnemonic) => (dispatch) =>
  async_api(dispatch, add_key(mnemonic, 'skip', null), true).then(
    (response) => {
      if (response.data.success) {
        // Go to wallet
        dispatch(resetMnemonic());
        dispatch(format_message('get_public_keys', {}));
        dispatch(refreshAllState());
        dispatch(push('/dashboard'));
      } else {
        if (response.data.word) {
          dispatch(setIncorrectWord(response.data.word));
          dispatch(push('/wallet/import'));
        } else if (response.data.error === 'Invalid order of mnemonic words') {
          dispatch(push('/wallet/import'));
        }
        const { error } = response.data;
        dispatch(openErrorDialog(error));
      }
    },
  );

export const add_and_restore_from_backup = (mnemonic, file_path) => (
  dispatch,
) =>
  async_api(
    dispatch,
    add_key(mnemonic, 'restore_backup', file_path),
    true,
  ).then((response) => {
    if (response.data.success) {
      // Go to wallet
      dispatch(resetMnemonic());
      dispatch(refreshAllState());
    } else {
      if (response.data.word) {
        dispatch(setIncorrectWord(response.data.word));
        dispatch(push('/wallet/import'));
      } else if (response.data.error === 'Invalid order of mnemonic words') {
        dispatch(push('/wallet/import'));
      }
      const { error } = response.data;
      dispatch(openErrorDialog(error));
    }
  });

export const delete_key = (fingerprint) => {
  const action = walletMessage();
  action.message.command = 'delete_key';
  action.message.data = { fingerprint };
  return action;
};

export const delete_all_keys = () => {
  const action = walletMessage();
  action.message.command = 'delete_all_keys';
  action.message.data = {};
  return action;
};

export const log_in = (fingerprint) => {
  const action = walletMessage();
  action.message.command = 'log_in';
  action.message.data = {
    fingerprint,
    host: backup_host,
    type: 'normal',
  };
  return action;
};

export const log_in_and_skip_import = (fingerprint) => {
  const action = walletMessage();
  action.message.command = 'log_in';
  action.message.data = {
    fingerprint,
    host: backup_host,
    type: 'skip',
  };
  return action;
};

export const log_in_and_import_backup = (fingerprint, file_path) => {
  const action = walletMessage();
  action.message.command = 'log_in';
  action.message.data = {
    fingerprint,
    type: 'restore_backup',
    file_path,
    host: backup_host,
  };
  return action;
};

export const log_in_and_import_backup_action = (fingerprint, file_path) => (
  dispatch,
) => {
  dispatch(selectFingerprint(fingerprint));
  return async_api(
    dispatch,
    log_in_and_import_backup(fingerprint, file_path),
    true,
  ).then((response) => {
    if (response.data.success) {
      // Go to wallet
      dispatch(refreshAllState());
      dispatch(push('/dashboard'));
    } else {
      const { error } = response.data;
      if (error === 'not_initialized') {
        dispatch(push('/wallet/restore'));
        // Go to restore from backup screen
      } else {
        dispatch(openErrorDialog(error));
      }
    }
  });
};

export const login_and_skip_action = (fingerprint) => (dispatch) => {
  dispatch(selectFingerprint(fingerprint));
  return async_api(dispatch, log_in_and_skip_import(fingerprint), true).then(
    (response) => {
      if (response.data.success) {
        // Go to wallet
        dispatch(refreshAllState());
        dispatch(push('/dashboard'));
      } else {
        const { error } = response.data;
        if (error === 'not_initialized') {
          dispatch(push('/wallet/restore'));
          // Go to restore from backup screen
        } else {
          dispatch(openErrorDialog(error));
        }
      }
    },
  );
};

export const login_action = (fingerprint) => (dispatch) => {
  dispatch(selectFingerprint(fingerprint));
  return async_api(dispatch, log_in(fingerprint), true).then((response) => {
    if (response.data.success) {
      // Go to wallet
      dispatch(refreshAllState());
      dispatch(push('/dashboard'));
    } else {
      const { error } = response.data;
      if (error === 'not_initialized') {
        const { backup_info } = response.data;
        const { backup_path } = response.data;
        dispatch(push('/wallet/restore'));
        if (backup_info && backup_path) {
          dispatch(setBackupInfo(backup_info));
          dispatch(selectFilePath(backup_path));
          dispatch(changeBackupView(presentBackupInfo));
        }
        // Go to restore from backup screen
      } else {
        dispatch(openErrorDialog(error));
      }
    }
  });
};

export const get_backup_info = (file_path, fingerprint, words) => {
  const action = walletMessage();
  action.message.command = 'get_backup_info';
  if (fingerprint === null) {
    action.message.data = {
      file_path,
      words,
    };
  } else if (words === null) {
    action.message.data = {
      file_path,
      fingerprint,
    };
  }
  return action;
};

export const get_backup_info_action = (file_path, fingerprint, words) => (
  dispatch,
) => {
  dispatch(selectFilePath(file_path));
  return async_api(
    dispatch,
    get_backup_info(file_path, fingerprint, words),
    true,
  ).then((response) => {
    if (response.data.success) {
      response.data.backup_info.downloaded = false;
      dispatch(setBackupInfo(response.data.backup_info));
      dispatch(changeBackupView(presentBackupInfo));
    } else {
      const { error } = response.data;
      dispatch(openErrorDialog(error));
    }
  });
};

export const get_private_key = (fingerprint) => {
  const action = walletMessage();
  action.message.command = 'get_private_key';
  action.message.data = { fingerprint };
  return action;
};

export const get_transactions = (wallet_id) => {
  const action = walletMessage();
  action.message.command = 'get_transactions';
  action.message.data = { wallet_id };
  return action;
};

export const get_address = (wallet_id, new_address) => {
  const action = walletMessage();
  action.message.command = 'get_next_address';
  action.message.data = { wallet_id, new_address };
  return action;
};

export const farm_block = (address) => {
  const action = walletMessage();
  action.message.command = 'farm_block';
  action.message.data = { address };
  return action;
};

export const get_height_info = () => {
  const action = walletMessage();
  action.message.command = 'get_height_info';
  action.message.data = {};
  return action;
};

export const getNetworkInfo = () => {
  const action = walletMessage();
  action.message.command = 'get_network_info';
  action.message.data = {};
  return action;
};

export const get_sync_status = () => {
  const action = walletMessage();
  action.message.command = 'get_sync_status';
  action.message.data = {};
  return action;
};

export const get_connection_info = () => {
  const action = walletMessage();
  action.message.command = 'get_connections';
  action.message.data = {};
  return action;
};

export const create_coloured_coin = (amount, fee) => {
  const action = walletMessage();
  action.message.command = 'create_new_wallet';
  action.message.data = {
    wallet_type: 'cc_wallet',
    mode: 'new',
    amount,
    fee,
    host: backup_host,
  };
  return action;
};

export const create_cc_for_colour = (colour, fee) => {
  const action = walletMessage();
  action.message.command = 'create_new_wallet';
  action.message.data = {
    wallet_type: 'cc_wallet',
    mode: 'existing',
    colour,
    fee,
    host: backup_host,
  };
  return action;
};

export const create_backup = (file_path) => {
  const action = walletMessage();
  action.message.command = 'create_backup';
  action.message.data = {
    file_path,
  };
  return action;
};

export const create_backup_action = (file_path) => (dispatch) =>
  async_api(dispatch, create_backup(file_path), true).then((response) => {
    if (response.data.success) {
      dispatch(showCreateBackup(false));
    } else {
      const { error } = response.data;
      dispatch(openErrorDialog(error));
    }
  });

export const create_cc_action = (amount, fee) => (dispatch) =>
  async_api(dispatch, create_coloured_coin(amount, fee), true).then(
    (response) => {
      dispatch(createState(true, false));
      if (response.data.success) {
        // Go to wallet
        dispatch(format_message('get_wallets', {}));
        dispatch(showCreateBackup(true));
        dispatch(createState(true, false));
        dispatch(changeCreateWallet(ALL_OPTIONS));
      } else {
        const { error } = response.data;
        dispatch(openErrorDialog(error));
      }
    },
  );

export const create_cc_for_colour_action = (colour, fee) => (dispatch) =>
  async_api(dispatch, create_cc_for_colour(colour, fee), true).then(
    (response) => {
      dispatch(createState(true, false));
      if (response.data.success) {
        // Go to wallet
        dispatch(showCreateBackup(true));
        dispatch(format_message('get_wallets', {}));
        dispatch(changeCreateWallet(ALL_OPTIONS));
      } else {
        const { error } = response.data;
        dispatch(openErrorDialog(error));
      }
    },
  );

export const get_colour_info = (wallet_id) => {
  const action = walletMessage();
  action.message.command = 'cc_get_colour';
  action.message.data = { wallet_id };
  return action;
};

export const get_colour_name = (wallet_id) => {
  const action = walletMessage();
  action.message.command = 'cc_get_name';
  action.message.data = { wallet_id };
  return action;
};

export const rename_cc_wallet = (wallet_id, name) => {
  const action = walletMessage();
  action.message.command = 'cc_set_name';
  action.message.data = { wallet_id, name };
  return action;
};

export const cc_spend = (wallet_id, address, amount, fee) => {
  const action = walletMessage();
  action.message.command = 'cc_spend';
  action.message.data = {
    wallet_id,
    inner_address: address,
    amount,
    fee,
  };
  return action;
};

export const logOut = (command, data) => ({ type: 'LOG_OUT', command, data });

export const incomingMessage = (message) => ({
  type: 'INCOMING_MESSAGE',
  message,
});

export const create_rl_admin = (interval, limit, pubkey, amount) => {
  const action = walletMessage();
  action.message.command = 'create_new_wallet';
  action.message.data = {
    wallet_type: 'rl_wallet',
    rl_type: 'admin',
    interval,
    limit,
    pubkey,
    amount,
    host: backup_host,
  };
  return action;
};

export const create_rl_admin_action = (interval, limit, pubkey, amount) => (
  dispatch,
) =>
  async_api(
    dispatch,
    create_rl_admin(interval, limit, pubkey, amount),
    true,
  ).then((response) => {
    dispatch(createState(true, false));
    if (response.data.success) {
      // Go to wallet
      dispatch(format_message('get_wallets', {}));
      dispatch(showCreateBackup(true));
      dispatch(createState(true, false));
      dispatch(changeCreateWallet(ALL_OPTIONS));
    } else {
      const { error } = response.data;
      dispatch(openErrorDialog(error));
    }
  });

export const create_rl_user = () => {
  const action = walletMessage();
  action.message.command = 'create_new_wallet';
  action.message.data = {
    wallet_type: 'rl_wallet',
    rl_type: 'user',
    host: backup_host,
  };
  return action;
};

export const create_rl_user_action = () => (dispatch) =>
  async_api(dispatch, create_rl_user(), true).then((response) => {
    dispatch(createState(true, false));
    if (response.data.success) {
      // Go to wallet
      dispatch(format_message('get_wallets', {}));
      dispatch(createState(true, false));
      dispatch(changeCreateWallet(ALL_OPTIONS));
    } else {
      const { error } = response.data;
      dispatch(openErrorDialog(error));
    }
  });

export const add_plot_directory_and_refresh = (dir) => (dispatch) =>
  async_api(dispatch, addPlotDirectory(dir), true).then((response) => {
    if (response.data.success) {
      dispatch(getPlotDirectories());
      return async_api(dispatch, refreshPlots(), true).then((response) => {
        dispatch(getPlots());
      });
    }
    const { error } = response.data;
    dispatch(openErrorDialog(error));
  });

export const remove_plot_directory_and_refresh = (dir) => (dispatch) =>
  async_api(dispatch, removePlotDirectory(dir), true).then((response) => {
    if (response.data.success) {
      dispatch(getPlotDirectories());
      return async_api(dispatch, refreshPlots(), true).then((response) => {
        dispatch(getPlots());
      });
    }
    const { error } = response.data;
    dispatch(openErrorDialog(error));
  });

export const rl_set_user_info = (
  wallet_id,
  interval,
  limit,
  origin,
  admin_pubkey,
) => {
  const action = walletMessage();
  action.message.command = 'rl_set_user_info';
  action.message.data = {
    wallet_id,
    interval,
    limit,
    origin,
    admin_pubkey,
  };
  return action;
};

export const rl_set_user_info_action = (
  wallet_id,
  interval,
  limit,
  origin,
  admin_pubkey,
) => (dispatch) =>
  async_api(
    dispatch,
    rl_set_user_info(wallet_id, interval, limit, origin, admin_pubkey),
    true,
  ).then((response) => {
    dispatch(createState(true, false));
    if (response.data.success) {
      // Go to wallet
      dispatch(format_message('get_wallets', {}));
      dispatch(showCreateBackup(true));
      dispatch(createState(true, false));
    } else {
      const { error } = response.data;
      dispatch(openErrorDialog(error));
    }
  });

export const clawback_rl_coin = (wallet_id) => {
  // THIS IS A PLACEHOLDER FOR RL CLAWBACK FUNCTIONALITY
};

export const exit_and_close = (event) => (dispatch) =>
  async_api(dispatch, exitDaemon(), false).then((response) => {
    dispatch(wsDisconnect());
    event.sender.send('daemon-exited');
  });

export const create_did_wallet = (
  amount,
  backup_dids,
  num_of_backup_ids_needed,
) => {
  const action = walletMessage();
  action.message.command = 'create_new_wallet';
  action.message.data = {
    wallet_type: 'did_wallet',
    did_type: 'new',
    amount,
    backup_dids,
    num_of_backup_ids_needed,
    host: backup_host,
  };
  return action;
};

export const create_did_action = (
  amount,
  backup_dids,
  num_of_backup_ids_needed,
) => (dispatch) =>
  async_api(
    dispatch,
    create_did_wallet(amount, backup_dids, num_of_backup_ids_needed),
    true,
  ).then((response) => {
    dispatch(createState(true, false));
    if (response.data.success) {
      // Go to wallet
      dispatch(format_message('get_wallets', {}));
      dispatch(showCreateBackup(true));
      dispatch(createState(true, false));
      dispatch(changeCreateWallet(ALL_OPTIONS));
    } else {
      const { error } = response.data;
      dispatch(openErrorDialog(error));
    }
  });

export const recover_did_wallet = (filename) => {
  const action = walletMessage();
  action.message.command = 'create_new_wallet';
  action.message.data = {
    wallet_type: 'did_wallet',
    did_type: 'recovery',
    filename,
    host: backup_host,
  };
  return action;
};

export const recover_did_action = (filename) => (dispatch) =>
  async_api(dispatch, recover_did_wallet(filename), true).then((response) => {
    dispatch(createState(true, false));
    if (response.data.success) {
      // Go to wallet
      dispatch(format_message('get_wallets', {}));
      dispatch(showCreateBackup(false));
      dispatch(createState(true, false));
      dispatch(changeCreateWallet(ALL_OPTIONS));
    } else {
      const { error } = response.data;
      dispatch(openErrorDialog(error));
    }
  });

export const did_update_recovery_ids = (
  wallet_id,
  new_list,
  num_verifications_required,
) => {
  const action = walletMessage();
  action.message.command = 'did_update_recovery_ids';
  action.message.data = {
    wallet_id,
    new_list,
    num_verifications_required,
  };
  return action;
};

export const did_update_recovery_ids_action = (
  wallet_id,
  new_list,
  num_verifications_required,
) => (dispatch) =>
  async_api(
    dispatch,
    did_update_recovery_ids(wallet_id, new_list, num_verifications_required),
    true,
  ).then((response) => {
    dispatch(format_message('get_wallets', {}));
    dispatch(createState(true, false));
  });

export const did_spend = (wallet_id, puzzlehash) => {
  const action = walletMessage();
  action.message.command = 'did_spend';
  action.message.data = { wallet_id, puzzlehash };
  return action;
};

export const did_get_did = (wallet_id) => {
  const action = walletMessage();
  action.message.command = 'did_get_did';
  action.message.data = { wallet_id };
  return action;
};

export const did_get_recovery_list = (wallet_id) => {
  const action = walletMessage();
  action.message.command = 'did_get_recovery_list';
  action.message.data = { wallet_id };
  return action;
};

export const did_recovery_spend = (
  wallet_id,
  spend_bundles,
  info_dict,
  coin_name,
  puzhash,
) => {
  const action = walletMessage();
  action.message.command = 'did_recovery_spend';
  action.message.data = {
    wallet_id,
    spend_bundles,
    info_dict,
    coin_name,
    puzhash,
  };
  return action;
};

export const did_create_attest = (wallet_id, coin_name, pubkey, puzhash) => {
  const action = walletMessage();
  action.message.command = 'did_create_attest';
  action.message.data = {
    wallet_id,
    coin_name,
    pubkey,
    puzhash,
  };
  return action;
};

export const did_generate_backup_file = (wallet_id, filename) => {
  const action = walletMessage();
  action.message.command = 'did_create_backup_file';
  action.message.data = {
    wallet_id,
    filename,
  };
  return action;
};
