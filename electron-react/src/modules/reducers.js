import { combineReducers } from 'redux';
import { websocketReducer } from './websocket';
import {incomingReducer} from './incoming_api';
import {mnemonicReducer} from './mnemonic_input';

const rootReducer = combineReducers({
  websocket: websocketReducer,
  wallet_state: incomingReducer,
  mnemonic_state: mnemonicReducer
});

export default rootReducer;
