import { combineReducers } from 'redux';
import { websocketReducer } from './websocket';
import {incomingReducer} from './incoming_api';
import {mnemonicReducer} from './mnemonic_input';
import {mainMenuReducer} from './mainMenu'
import {walletMenuReducer} from './walletMenu'
import {createWalletReducer} from './createWalletReducer'

const rootReducer = combineReducers({
  websocket: websocketReducer,
  wallet_state: incomingReducer,
  mnemonic_state: mnemonicReducer,
  main_menu: mainMenuReducer,
  wallet_menu: walletMenuReducer,
  create_options: createWalletReducer, 
});

export default rootReducer;
