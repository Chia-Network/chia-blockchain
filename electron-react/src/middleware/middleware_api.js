import {
  get_puzzle_hash,
  format_message,
  incomingMessage,
  get_balance_for_wallet,
  get_transactions,
  get_height_info,
  get_sync_status,
  get_connection_info,
  get_colour_info,
  get_colour_name,
  pingWallet
} from "../modules/message";

import { offerParsed, resetTrades } from "../modules/TradeReducer";
import { openDialog } from "../modules/dialogReducer";
import {
  service_wallet_server,
  service_full_node,
  service_simulator,
  service_farmer,
  service_harvester,
  service_plotter
} from "../util/service_names";
import {
  pingFullNode,
  getBlockChainState,
  getLatestBlocks,
  getFullNodeConnections
} from "../modules/fullnodeMessages";
import {
  getLatestChallenges,
  getFarmerConnections,
  pingFarmer
} from "../modules/farmerMessages";
import {
  getPlots,
  pingHarvester,
  refreshPlots
} from "../modules/harvesterMessages";
import { changeEntranceMenu, presentSelectKeys } from "../modules/entranceMenu";
import {
  addProgress,
  resetProgress,
  plottingStopped,
  plottingStarted
} from "../modules/plotter_messages";
import isElectron from "is-electron";
import { startService, isServiceRunning } from "../modules/daemon_messages";
import { get_all_trades } from "../modules/trade_messages";

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function ping_wallet(store) {
  store.dispatch(pingWallet());
  await sleep(300);
  const state = store.getState();
  const wallet_connected = state.daemon_state.wallet_connected;
  if (!wallet_connected) {
    ping_wallet(store);
  }
}

async function ping_full_node(store) {
  store.dispatch(pingFullNode());
  await sleep(300);
  const state = store.getState();
  const node_connected = state.daemon_state.full_node_connected;
  if (!node_connected) {
    ping_full_node(store);
  }
}

async function ping_farmer(store) {
  store.dispatch(pingFarmer());
  await sleep(300);
  const state = store.getState();
  const farmer_connected = state.daemon_state.farmer_connected;
  if (!farmer_connected) {
    ping_farmer(store);
  }
}

async function ping_harvester(store) {
  store.dispatch(pingHarvester());
  await sleep(300);
  const state = store.getState();
  const harvester_connected = state.daemon_state.harvester_connected;
  if (!harvester_connected) {
    ping_harvester(store);
  }
}

let global_tail = null;

async function track_progress(store, location) {
  if (!isElectron()) {
    return;
  }
  const Tail = window.require("tail").Tail;

  const dispatch = store.dispatch;
  var options = { fromBeginning: true, follow: true, useWatchFile: true };
  if (!location) {
    return;
  }
  dispatch(plottingStarted());
  try {
    dispatch(resetProgress());
    if (global_tail) {
      global_tail.unwatch();
    }
    global_tail = new Tail(location, options);
    global_tail.on("line", data => {
      dispatch(addProgress(data));
      if (
        data.includes("Copied final file") ||
        data.includes("Moved final file")
      ) {
        dispatch(refreshPlots());
      }
    });
    global_tail.on("error", err => {
      dispatch(addProgress(err));
    });
  } catch (e) {
    console.log(e);
  }
}

export const refreshAllState = dispatch => {
  dispatch(format_message("get_wallets", {}));
  let start_farmer = startService(service_farmer);
  let start_harvester = startService(service_harvester);
  dispatch(start_farmer);
  dispatch(start_harvester);
  dispatch(get_height_info());
  dispatch(get_sync_status());
  dispatch(get_connection_info());
  dispatch(getBlockChainState());
  dispatch(getLatestBlocks());
  dispatch(getFullNodeConnections());
  dispatch(getLatestChallenges());
  dispatch(getFarmerConnections());
  dispatch(getPlots());
  dispatch(isServiceRunning(service_plotter));
  dispatch(get_all_trades());
};

export const handle_message = (store, payload) => {
  store.dispatch(incomingMessage(payload));
  if (payload.command === "ping") {
    if (payload.origin === service_wallet_server) {
      store.dispatch(get_connection_info());
      store.dispatch(format_message("get_public_keys", {}));
    } else if (payload.origin === service_full_node) {
      store.dispatch(getBlockChainState());
      store.dispatch(getLatestBlocks());
      store.dispatch(getFullNodeConnections());
    } else if (payload.origin === service_farmer) {
      store.dispatch(getLatestChallenges());
      store.dispatch(getFarmerConnections());
    } else if (payload.origin === service_harvester) {
      store.dispatch(getPlots());
    }
  } else if (payload.command === "delete_key") {
    if (payload.data.success) {
      store.dispatch(format_message("get_public_keys", {}));
    }
  } else if (payload.command === "delete_all_keys") {
    if (payload.data.success) {
      store.dispatch(format_message("get_public_keys", {}));
    }
  } else if (payload.command === "get_public_keys") {
    if (payload.data.success) {
      store.dispatch(changeEntranceMenu(presentSelectKeys));
    }
  } else if (payload.command === "get_private_key") {
    const text =
      "Private key: " +
      payload.data.private_key.sk +
      "\n" +
      "Public key: " +
      payload.data.private_key.pk +
      "\n" +
      (payload.data.private_key.seed
        ? "seed: " + payload.data.private_key.seed
        : "No 24 word seed, since this key is imported.");
    store.dispatch(
      openDialog("Private key " + payload.data.private_key.fingerprint, text)
    );
  } else if (payload.command === "delete_plot") {
    store.dispatch(refreshPlots());
  } else if (payload.command === "refresh_plots") {
    store.dispatch(getPlots());
  } else if (payload.command === "get_wallets") {
    if (payload.data.success) {
      const wallets = payload.data.wallets;
      for (let wallet of wallets) {
        store.dispatch(get_balance_for_wallet(wallet.id));
        store.dispatch(get_transactions(wallet.id));
        store.dispatch(get_puzzle_hash(wallet.id));
        if (wallet.type === "COLOURED_COIN") {
          store.dispatch(get_colour_name(wallet.id));
          store.dispatch(get_colour_info(wallet.id));
        }
      }
    }
  } else if (payload.command === "state_changed") {
    const state = payload.data.state;
    if (state === "coin_added" || state === "coin_removed") {
      var wallet_id = payload.data.wallet_id;
      store.dispatch(get_balance_for_wallet(wallet_id));
      store.dispatch(get_transactions(wallet_id));
    } else if (state === "sync_changed") {
      store.dispatch(get_sync_status());
    } else if (state === "new_block") {
      store.dispatch(get_height_info());
    } else if (state === "pending_transaction") {
      wallet_id = payload.data.wallet_id;
      store.dispatch(get_balance_for_wallet(wallet_id));
      store.dispatch(get_transactions(wallet_id));
    }
  } else if (payload.command === "cc_set_name") {
    if (payload.data.success) {
      const wallet_id = payload.data.wallet_id;
      store.dispatch(get_colour_name(wallet_id));
    }
  } else if (payload.command === "respond_to_offer") {
    if (payload.data.success) {
      store.dispatch(openDialog("Success!", "Offer accepted"));
    }
    store.dispatch(resetTrades());
  } else if (payload.command === "get_discrepancies_for_offer") {
    if (payload.data.success) {
      store.dispatch(offerParsed(payload.data.discrepancies));
    }
  } else if (payload.command === "start_plotting") {
    if (payload.data.success) {
      track_progress(store, payload.data.out_file);
    }
  } else if (payload.command === "start_service") {
    const service = payload.data.service;
    if (payload.data.success) {
      if (service === service_wallet_server) {
        ping_wallet(store);
      } else if (service === service_full_node) {
        ping_full_node(store);
      } else if (service === service_simulator) {
        ping_full_node(store);
      } else if (service === service_farmer) {
        ping_farmer(store);
      } else if (service === service_harvester) {
        ping_harvester(store);
      } else if (service === service_plotter) {
        track_progress(store, payload.data.out_file);
      }
    } else if (payload.data.error === "already running") {
      if (service === service_wallet_server) {
        ping_wallet(store);
      } else if (service === service_full_node) {
        ping_full_node(store);
      } else if (service === service_simulator) {
        ping_full_node(store);
      } else if (service === service_farmer) {
        ping_farmer(store);
      } else if (service === service_harvester) {
        ping_harvester(store);
      } else if (service === service_plotter) {
      }
    }
  } else if (payload.command === "is_running") {
    if (payload.data.success) {
      const service = payload.data.service_name;
      const is_running = payload.data.is_running;
      if (service === service_plotter) {
        if (is_running) {
          track_progress(store, payload.data.out_file);
        }
      }
    }
  } else if (payload.command === "stop_service") {
    if (payload.data.success) {
      if (payload.data.service_name === service_plotter) {
        store.dispatch(plottingStopped());
      }
    }
  }
  if (payload.data.success === false) {
    if (payload.data.reason) {
      store.dispatch(openDialog("Error: ", payload.data.reason));
    }
  }
};
