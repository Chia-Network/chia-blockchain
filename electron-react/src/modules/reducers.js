import { combineReducers } from 'redux';
import { websocketReducer } from './websocket';
import {incomingReducer} from './incoming_api'


const rootReducer = combineReducers({
  websocket: websocketReducer,
  wallet_state: incomingReducer,
});

export default rootReducer;
