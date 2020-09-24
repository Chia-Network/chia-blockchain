import { combineReducers } from "redux";
import websocketReducer from "./websocket";
import incomingReducer from "./incoming";
import mnemonicReducer from "./mnemonic";
import walletMenuReducer from "./walletMenu";
import createWallet from "./createWallet";
import tradeReducer from "./trade";
import dialogReducer from "./dialog";
import daemonReducer from "./daemon";
import { entranceReducer } from "./entranceMenu";
import fullNodeReducer from "./fullNode";
import farmingReducer from "./farming";
import plotControlReducer from "./plotterControl";
import progressReducer from "./progress";
import backupReducer from "./backup";

const rootReducer = combineReducers({
  daemon_state: daemonReducer,
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
  plot_control: plotControlReducer,
  progress: progressReducer,
  backup_state: backupReducer
});

export type RootState = ReturnType<typeof rootReducer>;

export default rootReducer;
