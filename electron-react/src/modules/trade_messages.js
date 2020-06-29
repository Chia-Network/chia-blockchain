import { walletMessage } from "./message";
import { async } from "../util/header";
import { openProgress, closeProgress } from "./progressReducer";

export const cancel_trade = trade_id => {
  var action = walletMessage();
  action.message.command = "cancel_trade";
  const data = {
    trade_id: trade_id,
    secure: false
  };
  action.message.data = data;
  return action;
};

export const cancel_trade_with_spend = trade_id => {
  var action = walletMessage();
  action.message.command = "cancel_trade";
  const data = {
    trade_id: trade_id,
    secure: true
  };
  action.message.data = data;
  return action;
};

export const get_all_trades = () => {
  var action = walletMessage();
  action.message.command = "get_all_trades";
  const data = {};
  action.message.data = data;
  return action;
};

const async_api = (dispatch, action) => {
  dispatch(openProgress());
  var resolve_callback;
  var reject_callback;
  let myFirstPromise = new Promise((resolve, reject) => {
    resolve_callback = resolve;
    reject_callback = reject;
  });
  action.resolve_callback = resolve_callback;
  action.reject_callback = reject_callback;
  dispatch(action);
  return myFirstPromise;
};

export function cancel_trade_action(trade_id) {
  return dispatch => {
    return async_api(dispatch, cancel_trade(trade_id)).then(response => {
      dispatch(get_all_trades());
      dispatch(closeProgress());
    });
  };
}
