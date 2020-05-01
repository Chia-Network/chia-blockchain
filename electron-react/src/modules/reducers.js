import { combineReducers } from 'redux';
import { websocketReducer } from './websocket';

const rootReducer = combineReducers({
  websocket: websocketReducer,
});

export default rootReducer;
