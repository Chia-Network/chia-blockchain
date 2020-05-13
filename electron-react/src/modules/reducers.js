import { combineReducers } from "redux";
import { websocketReducer } from "./websocket";
import { incomingReducer } from "./incoming_api";
import { mnemonicReducer } from "./mnemonic_input";
import { mainMenuReducer } from "./mainMenu";
import { walletMenuReducer } from "./walletMenu";
import { createWalletReducer } from "./createWalletReducer";
import { tradeReducer } from "./TradeReducer";
import { dialogReducer } from "./dialogReducer";

const rootReducer = combineReducers({
  websocket: websocketReducer,
  wallet_state: incomingReducer,
  mnemonic_state: mnemonicReducer,
  main_menu: mainMenuReducer,
  wallet_menu: walletMenuReducer,
  create_options: createWalletReducer,
  trade_state: tradeReducer,
  dialog_state: dialogReducer
});

export default rootReducer;
