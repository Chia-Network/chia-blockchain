import { combineReducers } from 'redux';
import { History } from 'history';
import { connectRouter } from 'connected-react-router';
import websocketReducer from './websocket';
import incomingReducer from './incoming';
import mnemonicReducer from './mnemonic';
import walletMenuReducer from './walletMenu';
import createWallet from './createWallet';
import tradeReducer from './trade';
import dialogReducer from './dialog';
import daemonReducer from './daemon';
import keyringReducer from './keyring';
import { entranceReducer } from './entranceMenu';
import fullNodeReducer from './fullNode';
import farmingReducer from './farming';
import plotterConfigurationReducer from './plotterConfiguration';
import plotControlReducer from './plotterControl';
import plotQueueReducer from './plotQueue';
import plotNFTReducer from './plotNFT';
import progressReducer from './progress';
import backupReducer from './backup';
import localStorageReducer from './localStorage';

const reducers = {
  daemon_state: daemonReducer,
  keyring_state: keyringReducer,
  websocket: websocketReducer,
  wallet_state: incomingReducer,
  mnemonic_state: mnemonicReducer,
  wallet_menu: walletMenuReducer,
  create_options: createWallet,
  trade_state: tradeReducer,
  dialog_state: dialogReducer,
  entrance_menu: entranceReducer,
  full_node_state: fullNodeReducer,
  farming_state: farmingReducer,
  plotter_configuration: plotterConfigurationReducer,
  plot_control: plotControlReducer,
  progress: progressReducer,
  backup_state: backupReducer,
  plot_queue: plotQueueReducer,
  plot_nft: plotNFTReducer,
  local_storage: localStorageReducer,
};

const rootReducerWithoutRouter = combineReducers(reducers);

export type RootState = ReturnType<typeof rootReducerWithoutRouter>;

export function createRootReducer(history: History) {
  return combineReducers({
    ...reducers,
    router: connectRouter(history),
  });
}
