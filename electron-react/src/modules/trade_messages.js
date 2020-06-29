import { walletMessage } from "./message";

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
