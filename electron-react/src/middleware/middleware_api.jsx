import React from 'react';
import { AlertDialog } from '@chia/core';
import {
  get_address,
  format_message,
  incomingMessage,
  get_balance_for_wallet,
  get_transactions,
  get_height_info,
  get_sync_status,
  get_connection_info,
  get_colour_info,
  get_colour_name,
  pingWallet,
} from '../modules/message';

import { offerParsed, resetTrades } from '../modules/trade';
import { openDialog, openErrorDialog } from '../modules/dialog';
import {
  service_wallet,
  service_full_node,
  service_simulator,
  service_farmer,
  service_harvester,
  service_plotter,
} from '../util/service_names';
import {
  pingFullNode,
  getBlockChainState,
  getFullNodeConnections,
  updateLatestBlocks,
  updateUnfinishedSubBlockHeaders,
} from '../modules/fullnodeMessages';
import {
  getLatestChallenges,
  getFarmerConnections,
  pingFarmer,
} from '../modules/farmerMessages';
import {
  getPlots,
  getPlotDirectories,
  pingHarvester,
  refreshPlots,
} from '../modules/harvesterMessages';
import { plottingStopped } from '../modules/plotter_messages';

import { plotQueueUpdate } from '../modules/plotQueue';
import { startService, isServiceRunning } from '../modules/daemon_messages';
import { get_all_trades } from '../modules/trade_messages';
import {
  COLOURED_COIN,
  STANDARD_WALLET,
  RATE_LIMITED,
} from '../util/wallet_types';

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function ping_wallet(store) {
  store.dispatch(pingWallet());
  await sleep(1000);
  const state = store.getState();
  const { wallet_connected } = state.daemon_state;
  if (!wallet_connected) {
    ping_wallet(store);
  }
}

async function ping_full_node(store) {
  store.dispatch(pingFullNode());
  await sleep(1000);
  const state = store.getState();
  const node_connected = state.daemon_state.full_node_connected;
  if (!node_connected) {
    ping_full_node(store);
  }
}

async function ping_farmer(store) {
  store.dispatch(pingFarmer());
  await sleep(1000);
  const state = store.getState();
  const { farmer_connected } = state.daemon_state;
  if (!farmer_connected) {
    ping_farmer(store);
  }
}

async function ping_harvester(store) {
  store.dispatch(pingHarvester());
  await sleep(1000);
  const state = store.getState();
  const { harvester_connected } = state.daemon_state;
  if (!harvester_connected) {
    ping_harvester(store);
  }
}

export function refreshAllState() {
  return async (dispatch, getState) => {
    dispatch(format_message('get_wallets', {}));
    const start_farmer = startService(service_farmer);
    const start_harvester = startService(service_harvester);
    dispatch(start_farmer);
    dispatch(start_harvester);

    dispatch(get_height_info());
    dispatch(get_sync_status());
    dispatch(get_connection_info());

    dispatch(getFullNodeConnections());
    dispatch(getLatestChallenges());
    dispatch(getFarmerConnections());
    dispatch(getPlots());
    dispatch(getPlotDirectories());
    dispatch(get_all_trades());
  };
}

export const handle_message = async (store, payload) => {
  const { dispatch } = store;
  const { command } = payload;
  const stateBefore = store.getState();

  await store.dispatch(incomingMessage(payload));
  if (command === 'get_blockchain_state') {
    const state = store.getState();

    if (
      stateBefore.full_node_state?.blockchain_state?.peak
        ?.reward_chain_sub_block?.sub_block_height !==
      state.full_node_state?.blockchain_state?.peak?.reward_chain_sub_block
        ?.sub_block_height
    ) {
      dispatch(updateLatestBlocks());
      dispatch(updateUnfinishedSubBlockHeaders());
    }
  } else if (payload.command === 'ping') {
    if (payload.origin === service_wallet) {
      store.dispatch(get_connection_info());
      store.dispatch(format_message('get_public_keys', {}));
    } else if (payload.origin === service_full_node) {
      await store.dispatch(getBlockChainState());
      store.dispatch(getFullNodeConnections());
    } else if (payload.origin === service_farmer) {
      store.dispatch(getLatestChallenges());
      store.dispatch(getFarmerConnections());
    } else if (payload.origin === service_harvester) {
      // get plots is working only when harcester is connected
      const state = store.getState();
      if (!state.farming_state.harvester?.plots) {
        store.dispatch(getPlots());
      }
      if (!state.farming_state.harvester?.plot_directories) {
        store.dispatch(getPlotDirectories());
      }
    }
  } else if (payload.command === 'delete_key') {
    if (payload.data.success) {
      store.dispatch(format_message('get_public_keys', {}));
    }
  } else if (payload.command === 'delete_all_keys') {
    if (payload.data.success) {
      store.dispatch(format_message('get_public_keys', {}));
    }
  } else if (payload.command === 'get_public_keys') {
    /*
    if (payload.data.success) {
      console.log('redirect to / after get_public_keys');
      store.dispatch(push('/'));
    }
    */
  } else if (payload.command === 'get_private_key') {
    const text =
      `Private key: ${payload.data.private_key.sk}\n` +
      `Public key: ${payload.data.private_key.pk}\n${
        payload.data.private_key.seed
          ? `seed: ${payload.data.private_key.seed}`
          : 'No 24 word seed, since this key is imported.'
      }`;
    store.dispatch(
      openDialog(
        <AlertDialog
          title={`Private key ${payload.data.private_key.fingerprint}`}
        >
          {text}
        </AlertDialog>,
      ),
    );
  } else if (payload.command === 'delete_plot') {
    store.dispatch(refreshPlots());
  } else if (payload.command === 'refresh_plots') {
    store.dispatch(getPlots());
  } else if (payload.command === 'get_wallets') {
    if (payload.data.success) {
      const { wallets } = payload.data;
      for (const wallet of wallets) {
        if (wallet.type === RATE_LIMITED) {
          const data = JSON.parse(wallet.data);
          wallet.data = data;
          if (data.initialized === true) {
            store.dispatch(get_balance_for_wallet(wallet.id));
          } else {
            console.log('RL wallet has not been initalized yet');
          }
        } else {
          store.dispatch(get_balance_for_wallet(wallet.id));
        }
        store.dispatch(get_transactions(wallet.id));
        if (wallet.type === COLOURED_COIN || wallet.type === STANDARD_WALLET) {
          store.dispatch(get_address(wallet.id));
        }
        if (wallet.type === COLOURED_COIN) {
          store.dispatch(get_colour_name(wallet.id));
          store.dispatch(get_colour_info(wallet.id));
        }
      }
    }
  } else if (payload.command === 'register_service') {
    const { service, queue } = payload.data;
    if (service === service_plotter) {
      store.dispatch(plotQueueUpdate(queue));
    }
  } else if (payload.command === 'state_changed') {
    const { origin } = payload;
    const { state } = payload.data;

    if (origin === service_plotter) {
      const { queue } = payload.data;
      await store.dispatch(plotQueueUpdate(queue));

      // updated state of the plots
      if (state === 'state') {
        store.dispatch(refreshPlots());
      }
    } else {
      if (state === 'coin_added' || state === 'coin_removed') {
        var { wallet_id } = payload.data;
        store.dispatch(get_balance_for_wallet(wallet_id));
        store.dispatch(get_transactions(wallet_id));
      } else if (state === 'sync_changed') {
        store.dispatch(get_sync_status());
      } else if (state === 'new_block') {
        store.dispatch(get_height_info());
      } else if (state === 'pending_transaction') {
        wallet_id = payload.data.wallet_id;
        store.dispatch(get_balance_for_wallet(wallet_id));
        store.dispatch(get_transactions(wallet_id));
      }
    }
  } else if (payload.command === 'cc_set_name') {
    if (payload.data.success) {
      const { wallet_id } = payload.data;
      store.dispatch(get_colour_name(wallet_id));
    }
  } else if (payload.command === 'respond_to_offer') {
    if (payload.data.success) {
      store.dispatch(
        openDialog(<AlertDialog title="Success!">Offer accepted</AlertDialog>),
      );
    }
    store.dispatch(resetTrades());
  } else if (payload.command === 'get_discrepancies_for_offer') {
    if (payload.data.success) {
      store.dispatch(offerParsed(payload.data.discrepancies));
    }
  } else if (payload.command === 'start_service') {
    const { service } = payload.data;
    if (payload.data.success) {
      if (service === service_wallet) {
        ping_wallet(store);
      } else if (
        service === service_full_node ||
        service === service_simulator
      ) {
        ping_full_node(store);
      } else if (service === service_farmer) {
        ping_farmer(store);
      } else if (service === service_harvester) {
        ping_harvester(store);
      }
    } else if (payload.data.error.includes('already running')) {
      if (service === service_wallet) {
        ping_wallet(store);
      } else if (
        service === service_full_node ||
        service === service_simulator
      ) {
        ping_full_node(store);
      } else if (service === service_farmer) {
        ping_farmer(store);
      } else if (service === service_harvester) {
        ping_harvester(store);
      } else if (service === service_plotter) {
      }
    }
  } else if (payload.command === 'stop_service') {
    if (payload.data.success) {
      if (payload.data.service_name === service_plotter) {
        await store.dispatch(plottingStopped());
      }
    }
  }
  if (payload.data.success === false) {
    if (
      payload.data.error.includes('already running') ||
      payload.data.error === 'not_initialized'
    ) {
      return;
    }
    if (payload.data.error) {
      store.dispatch(openErrorDialog(payload.data.error));
    }
  }
};
