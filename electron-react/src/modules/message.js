import { service_wallet } from "../util/service_names";
import { openProgress, closeProgress } from "./progressReducer";
import { refreshAllState } from "../middleware/middleware_api";
import { setIncorrectWord, resetMnemonic } from "./mnemonic_input";
import {
  changeEntranceMenu,
  presentRestoreBackup,
  presentOldWallet
} from "./entranceMenu";
import { openDialog } from "./dialogReducer";
import { createState } from "./createWalletReducer";
import {
  addPlotDirectory,
  getPlotDirectories,
  removePlotDirectory,
  getPlots,
  refreshPlots
} from "./harvesterMessages";
import {
  setBackupInfo,
  changeBackupView,
  presentBackupInfo,
  selectFilePath
} from "./backup_state";

export const clearSend = () => {
  var action = {
    type: "CLEAR_SEND",
    mesasge: ""
  };
  return action;
};

export const walletMessage = () => ({
  type: "OUTGOING_MESSAGE",
  message: {
    destination: service_wallet
  }
});

export const selectFingerprint = fingerprint => ({
  type: "SELECT_FINGERPRINT",
  fingerprint: fingerprint
});

export const unselectFingerprint = () => ({
  type: "UNSELECT_FINGERPRINT"
});

export const selectMnemonic = mnemonic => ({
  type: "SELECT_MNEMONIC",
  mnemonic: mnemonic
});

export const showCreateBackup = show => ({
  type: "SHOW_CREATE_BACKUP",
  show: show
});

export const async_api = (dispatch, action, open_spinner) => {
  if (open_spinner === true) {
    dispatch(openProgress());
  }
  var resolve_callback;
  var reject_callback;
  let myFirstPromise = new Promise((resolve, reject) => {
    resolve_callback = resolve;
    reject_callback = reject;
  });
  action.resolve_callback = resolve_callback;
  action.reject_callback = reject_callback;
  dispatch(action);
  return myFirstPromise;
};

export const format_message = (command, data) => {
  var action = walletMessage();
  action.message.command = command;
  action.message.data = data;
  return action;
};

export const pingWallet = () => {
  var action = walletMessage();
  action.message.command = "ping";
  action.message.data = {};
  return action;
};

export const get_balance_for_wallet = id => {
  var action = walletMessage();
  action.message.command = "get_wallet_balance";
  action.message.data = { wallet_id: id };
  return action;
};

export const send_transaction = (wallet_id, amount, fee, puzzle_hash) => {
  var action = walletMessage();
  action.message.command = "send_transaction";
  action.message.data = {
    wallet_id: wallet_id,
    amount: amount,
    fee: fee,
    puzzle_hash: puzzle_hash
  };
  return action;
};

export const genereate_mnemonics = () => {
  var action = walletMessage();
  action.message.command = "generate_mnemonic";
  action.message.data = {};
  return action;
};

export const add_key = (mnemonic, type, file_path) => {
  var action = walletMessage();
  action.message.command = "add_key";
  action.message.data = {
    mnemonic: mnemonic,
    type: type,
    file_path: file_path
  };
  return action;
};

export const add_new_key_action = mnemonic => {
  return dispatch => {
    return async_api(
      dispatch,
      add_key(mnemonic, "new_wallet", null),
      true
    ).then(response => {
      dispatch(closeProgress());
      if (response.data.success) {
        // Go to wallet
        dispatch(resetMnemonic());
        dispatch(format_message("get_public_keys", {}));
        refreshAllState(dispatch);
      } else {
        if (response.data.word) {
          dispatch(setIncorrectWord(response.data.word));
          dispatch(changeEntranceMenu(presentOldWallet));
        } else if (response.data.error === "Invalid order of mnemonic words") {
          dispatch(changeEntranceMenu(presentOldWallet));
        }
        const error = response.data.error;
        dispatch(openDialog("Error", error));
      }
    });
  };
};

export const add_and_skip_backup = mnemonic => {
  return dispatch => {
    return async_api(dispatch, add_key(mnemonic, "skip", null), true).then(
      response => {
        dispatch(closeProgress());
        if (response.data.success) {
          // Go to wallet
          dispatch(resetMnemonic());
          dispatch(format_message("get_public_keys", {}));
          refreshAllState(dispatch);
        } else {
          if (response.data.word) {
            dispatch(setIncorrectWord(response.data.word));
            dispatch(changeEntranceMenu(presentOldWallet));
          } else if (
            response.data.error === "Invalid order of mnemonic words"
          ) {
            dispatch(changeEntranceMenu(presentOldWallet));
          }
          const error = response.data.error;
          dispatch(openDialog("Error", error));
        }
      }
    );
  };
};

export const add_and_restore_from_backup = (mnemonic, file_path) => {
  return dispatch => {
    return async_api(
      dispatch,
      add_key(mnemonic, "restore_backup", file_path),
      true
    ).then(response => {
      dispatch(closeProgress());
      if (response.data.success) {
        // Go to wallet
        dispatch(resetMnemonic());
        dispatch(format_message("get_public_keys", {}));
        refreshAllState(dispatch);
      } else {
        if (response.data.word) {
          dispatch(setIncorrectWord(response.data.word));
          dispatch(changeEntranceMenu(presentOldWallet));
        } else if (response.data.error === "Invalid order of mnemonic words") {
          dispatch(changeEntranceMenu(presentOldWallet));
        }
        const error = response.data.error;
        dispatch(openDialog("Error", error));
      }
    });
  };
};

export const delete_key = fingerprint => {
  var action = walletMessage();
  action.message.command = "delete_key";
  action.message.data = { fingerprint: fingerprint };
  return action;
};

export const delete_all_keys = () => {
  var action = walletMessage();
  action.message.command = "delete_all_keys";
  action.message.data = {};
  return action;
};

export const log_in = fingerprint => {
  var action = walletMessage();
  action.message.command = "log_in";
  action.message.data = { fingerprint: fingerprint, type: "normal" };
  return action;
};

export const log_in_and_skip_import = fingerprint => {
  var action = walletMessage();
  action.message.command = "log_in";
  action.message.data = { fingerprint: fingerprint, type: "skip" };
  return action;
};

export const log_in_and_import_backup = (fingerprint, file_path) => {
  var action = walletMessage();
  action.message.command = "log_in";
  action.message.data = {
    fingerprint: fingerprint,
    type: "restore_backup",
    file_path: file_path
  };
  return action;
};

export const login_and_skip_action = fingerprint => {
  return dispatch => {
    dispatch(selectFingerprint(fingerprint));
    return async_api(dispatch, log_in_and_skip_import(fingerprint), true).then(
      response => {
        dispatch(closeProgress());
        if (response.data.success) {
          // Go to wallet
          refreshAllState(dispatch);
        } else {
          const error = response.data.error;
          if (error === "not_initialized") {
            dispatch(changeEntranceMenu(presentRestoreBackup));
            // Go to restore from backup screen
          } else {
            dispatch(openDialog("Error", error));
          }
        }
      }
    );
  };
};

export const login_action = fingerprint => {
  return dispatch => {
    dispatch(selectFingerprint(fingerprint));
    return async_api(dispatch, log_in(fingerprint), true).then(response => {
      dispatch(closeProgress());
      if (response.data.success) {
        // Go to wallet
        refreshAllState(dispatch);
      } else {
        const error = response.data.error;
        if (error === "not_initialized") {
          dispatch(changeEntranceMenu(presentRestoreBackup));
          // Go to restore from backup screen
        } else {
          dispatch(openDialog("Error", error));
        }
      }
    });
  };
};

export const get_backup_info = (file_path, fingerprint, words) => {
  var action = walletMessage();
  action.message.command = "get_backup_info";
  if (fingerprint === null) {
    action.message.data = {
      file_path: file_path,
      words: words
    };
  } else if (words === null) {
    action.message.data = {
      file_path: file_path,
      fingerprint: fingerprint
    };
  }
  return action;
};

export const get_backup_info_action = (file_path, fingerprint, words) => {
  return dispatch => {
    dispatch(selectFilePath(file_path));
    return async_api(
      dispatch,
      get_backup_info(file_path, fingerprint, words),
      true
    ).then(response => {
      dispatch(closeProgress());
      if (response.data.success) {
        dispatch(setBackupInfo(response.data.backup_info));
        dispatch(changeBackupView(presentBackupInfo));
      } else {
        const error = response.data.error;
        dispatch(openDialog("Error", error));
      }
    });
  };
};

export const get_private_key = fingerprint => {
  var action = walletMessage();
  action.message.command = "get_private_key";
  action.message.data = { fingerprint: fingerprint };
  return action;
};

export const get_transactions = wallet_id => {
  var action = walletMessage();
  action.message.command = "get_transactions";
  action.message.data = { wallet_id: wallet_id };
  return action;
};

export const get_puzzle_hash = wallet_id => {
  var action = walletMessage();
  action.message.command = "get_next_puzzle_hash";
  action.message.data = { wallet_id: wallet_id };
  return action;
};

export const farm_block = puzzle_hash => {
  var action = walletMessage();
  action.message.command = "farm_block";
  action.message.data = { puzzle_hash: puzzle_hash };
  return action;
};

export const get_height_info = () => {
  var action = walletMessage();
  action.message.command = "get_height_info";
  action.message.data = {};
  return action;
};

export const get_sync_status = () => {
  var action = walletMessage();
  action.message.command = "get_sync_status";
  action.message.data = {};
  return action;
};

export const get_connection_info = () => {
  var action = walletMessage();
  action.message.command = "get_connections";
  action.message.data = {};
  return action;
};

export const create_coloured_coin = (amount, fee) => {
  var action = walletMessage();
  action.message.command = "create_new_wallet";
  action.message.data = {
    wallet_type: "cc_wallet",
    mode: "new",
    amount: amount,
    fee: fee
  };
  return action;
};

export const create_cc_for_colour = (colour, fee) => {
  var action = walletMessage();
  action.message.command = "create_new_wallet";
  action.message.data = {
    wallet_type: "cc_wallet",
    mode: "existing",
    colour: colour,
    fee: fee
  };
  return action;
};

export const create_backup = file_path => {
  var action = walletMessage();
  action.message.command = "create_backup";
  action.message.data = {
    file_path: file_path
  };
  return action;
};

export const create_backup_action = file_path => {
  return dispatch => {
    return async_api(dispatch, create_backup(file_path), true).then(
      response => {
        dispatch(closeProgress());
        if (response.data.success) {
          dispatch(showCreateBackup(false));
        } else {
          const error = response.data.error;
          dispatch(openDialog("Error", error));
        }
      }
    );
  };
};

export const create_cc_action = (amount, fee) => {
  return dispatch => {
    return async_api(dispatch, create_coloured_coin(amount, fee), true).then(
      response => {
        dispatch(closeProgress());
        dispatch(createState(true, false));
        if (response.data.success) {
          // Go to wallet
          dispatch(format_message("get_wallets", {}));
          dispatch(showCreateBackup(true));
          dispatch(createState(true, false));
        } else {
          const error = response.data.error;
          dispatch(openDialog("Error", error));
        }
      }
    );
  };
};

export const create_cc_for_colour_action = (colour, fee) => {
  return dispatch => {
    return async_api(dispatch, create_cc_for_colour(colour, fee), true).then(
      response => {
        dispatch(closeProgress());
        dispatch(createState(true, false));
        if (response.data.success) {
          // Go to wallet
          dispatch(showCreateBackup(true));
          dispatch(format_message("get_wallets", {}));
        } else {
          const error = response.data.error;
          dispatch(openDialog("Error", error));
        }
      }
    );
  };
};

export const get_colour_info = wallet_id => {
  var action = walletMessage();
  action.message.command = "cc_get_colour";
  action.message.data = { wallet_id: wallet_id };
  return action;
};

export const get_colour_name = wallet_id => {
  var action = walletMessage();
  action.message.command = "cc_get_name";
  action.message.data = { wallet_id: wallet_id };
  return action;
};

export const rename_cc_wallet = (wallet_id, name) => {
  var action = walletMessage();
  action.message.command = "cc_set_name";
  action.message.data = { wallet_id: wallet_id, name: name };
  return action;
};

export const cc_spend = (wallet_id, puzzle_hash, amount, fee) => {
  var action = walletMessage();
  action.message.command = "cc_spend";
  action.message.data = {
    wallet_id: wallet_id,
    innerpuzhash: puzzle_hash,
    amount: amount,
    fee: fee
  };
  return action;
};

export const logOut = (command, data) => ({ type: "LOG_OUT", command, data });

export const incomingMessage = message => ({
  type: "INCOMING_MESSAGE",
  message: message
});

export const create_rl_admin = (interval, limit, pubkey, amount) => {
  var action = walletMessage();
  action.message.command = "create_new_wallet";
  action.message.data = {
    wallet_type: "rl_wallet",
    rl_type: "admin",
    interval: interval,
    limit: limit,
    pubkey: pubkey,
    amount: amount
  };
  console.log("CREATE RL ADMIN ACTION: ", action)
  return action;
};

export const create_rl_admin_action = (interval, limit, pubkey, amount) => {
  return dispatch => {
    return async_api(dispatch, create_rl_admin(interval, limit, pubkey, amount), true).then(
      response => {
        dispatch(closeProgress());
        dispatch(createState(true, false));
        if (response.data.success) {
          // Go to wallet
          dispatch(format_message("get_wallets", {}));
          dispatch(showCreateBackup(true));
          dispatch(createState(true, false));
        } else {
          const error = response.data.error;
          dispatch(openDialog("Error", error));
        }
      }
    );
  };
};

export const create_rl_user = () => {
  var action = walletMessage();
  action.message.command = "create_new_wallet";
  action.message.data = {
    wallet_type: "rl_wallet",
    rl_type: "user"
  };
  console.log("CREATE RL USER ACTION: ", action)
  return action;
};

export const create_rl_user_action = () => {
  return dispatch => {
    return async_api(dispatch, create_rl_user(), true).then(
      response => {
        dispatch(closeProgress());
        dispatch(createState(true, false));
        if (response.data.success) {
          // Go to wallet
          dispatch(format_message("get_wallets", {}));
          dispatch(createState(true, false));
        } else {
          const error = response.data.error;
          dispatch(openDialog("Error", error));
        }
      }
    );
  };
};

export const add_plot_directory_and_refresh = dir => {
  return dispatch => {
    return async_api(dispatch, addPlotDirectory(dir), true).then(response => {
      if (response.data.success) {
        dispatch(getPlotDirectories());
        return async_api(dispatch, refreshPlots(), false).then(response => {
          dispatch(closeProgress());
          dispatch(getPlots());
        });
      } else {
        const error = response.data.error;
        dispatch(openDialog("Error", error));
      }
    });
  };
};

export const remove_plot_directory_and_refresh = dir => {
  return dispatch => {
    return async_api(dispatch, removePlotDirectory(dir), true).then(
      response => {
        if (response.data.success) {
          dispatch(getPlotDirectories());
          return async_api(dispatch, refreshPlots(), false).then(response => {
            dispatch(closeProgress());
            dispatch(getPlots());
          });
        } else {
          const error = response.data.error;
          dispatch(openDialog("Error", error));
        }
      }
    );
  };
};

export const rl_set_user_info = (wallet_id, interval, limit, origin, admin_pubkey) => {
  var action = walletMessage();
  action.message.command = "rl_set_user_info";
  action.message.data = {
    wallet_id: wallet_id,
    interval: interval,
    limit: limit,
    origin: origin,
    admin_pubkey: admin_pubkey
  };
  console.log("RL SET USER INFO ACTION: ", action)
  return action;
};

export const rl_set_user_info_action = (wallet_id, interval, limit, origin, admin_pubkey) => {
  return dispatch => {
    return async_api(dispatch, rl_set_user_info(wallet_id, interval, limit, origin, admin_pubkey), true).then(
      response => {
        dispatch(closeProgress());
        dispatch(createState(true, false));
        if (response.data.success) {
          // Go to wallet
          dispatch(format_message("get_wallets", {}));
          dispatch(showCreateBackup(false));
          dispatch(createState(true, false));
        } else {
          const error = response.data.error;
          dispatch(openDialog("Error", error));
        }
      }
    );
  };
};

export const clawback_rl_coin = (wallet_id) => {
  // THIS IS A PLACEHOLDER FOR RL CLAWBACK FUNCTIONALITY
}