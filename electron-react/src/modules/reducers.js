import { combineReducers } from "redux";
import { websocketReducer } from "./websocket";
import { incomingReducer } from "./incoming_api";
import { mnemonicReducer } from "./mnemonic_input";
import { mainMenuReducer } from "./mainMenu";
import { walletMenuReducer } from "./walletMenu";
import { createWalletReducer } from "./createWalletReducer";
import { tradeReducer } from "./TradeReducer";
import { dialogReducer } from "./dialogReducer";
import { daemonReducer } from "./daemon_api";
import { entranceReducer } from "./entranceMenu";
import { fullnodeReducer } from "./fullnode_api";

const rootReducer = combineReducers({
  daemon_state: daemonReducer,
  websocket: websocketReducer,
  wallet_state: incomingReducer,
  mnemonic_state: mnemonicReducer,
  main_menu: mainMenuReducer,
  wallet_menu: walletMenuReducer,
  create_options: createWalletReducer,
  trade_state: tradeReducer,
  dialog_state: dialogReducer,
  entrance_menu: entranceReducer,
  full_node_state: fullnodeReducer
});

export default rootReducer;
