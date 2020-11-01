import { walletMessage, async_api } from './message';
import { closeProgress } from './progress';

export const cancel_trade = (trade_id) => {
  const action = walletMessage();
  action.message.command = 'cancel_trade';
  const data = {
    trade_id,
    secure: false,
  };
  action.message.data = data;
  return action;
};

export const cancel_trade_with_spend = (trade_id) => {
  const action = walletMessage();
  action.message.command = 'cancel_trade';
  const data = {
    trade_id,
    secure: true,
  };
  action.message.data = data;
  return action;
};

export const get_all_trades = () => {
  const action = walletMessage();
  action.message.command = 'get_all_trades';
  const data = {};
  action.message.data = data;
  return action;
};

export function cancel_trade_action(trade_id) {
  return (dispatch) => {
    return async_api(dispatch, cancel_trade(trade_id)).then((response) => {
      dispatch(get_all_trades());
      dispatch(closeProgress());
    });
  };
}

export function cancel_trade_with_spend_action(trade_id) {
  return (dispatch) => {
    return async_api(dispatch, cancel_trade_with_spend(trade_id)).then(
      (response) => {
        dispatch(get_all_trades());
        dispatch(closeProgress());
      },
    );
  };
}

export const create_trade_offer = (trades, filepath) => {
  const action = walletMessage();
  action.message.command = 'create_offer_for_ids';
  const data = {
    ids: trades,
    filename: filepath,
  };
  action.message.data = data;
  return action;
};

export const parse_trade_offer = (filepath) => {
  const action = walletMessage();
  action.message.command = 'get_discrepancies_for_offer';
  const data = { filename: filepath };
  action.message.data = data;
  return action;
};

export const accept_trade_offer = (filepath) => {
  const action = walletMessage();
  action.message.command = 'respond_to_offer';
  action.message.data = { filename: filepath };
  return action;
};

export function create_trade_action(trades, filepath, history) {
  return (dispatch) => {
    return async_api(dispatch, create_trade_offer(trades, filepath)).then(
      (response) => {
        dispatch(get_all_trades());
        history.push('/dashboard/trade');
        dispatch(closeProgress());
      },
    );
  };
}

export function parse_trade_action(filepath) {
  return (dispatch) => {
    return async_api(dispatch, parse_trade_offer(filepath)).then((response) => {
      dispatch(get_all_trades());
      dispatch(closeProgress());
    });
  };
}

export function accept_trade_action(filepath) {
  return (dispatch) => {
    return async_api(dispatch, accept_trade_offer(filepath)).then(
      (response) => {
        dispatch(get_all_trades());
        dispatch(closeProgress());
      },
    );
  };
}
