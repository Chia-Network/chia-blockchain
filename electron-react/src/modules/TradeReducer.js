import { service_wallet } from "../util/service_names";

export const addTrade = trade => ({ type: "TRADE_ADDED", trade });
export const resetTrades = () => ({ type: "RESET_TRADE" });
export const presentTrade = trade => ({ type: "PRESENT_TRADES", trade });
export const presetOverview = () => ({ type: "PRESENT_OVERVIEW" });

export const newBuy = (amount, id) => ({
  amount: amount,
  wallet_id: id,
  side: "buy"
});

export const newSell = (amount, id) => ({
  amount: amount,
  wallet_id: id,
  side: "sell"
});

export const offerParsed = offer => ({
  type: "OFFER_PARSING",
  status: parsingStateParsed,
  offer: offer
});
export const offerParsingName = (name, path) => ({
  type: "OFFER_NAME",
  name: name,
  path: path
});
export const parsingStarted = () => ({
  type: "OFFER_PARSING",
  status: parsingStatePending
});

export const parsingStateNone = "NONE";
export const parsingStatePending = "PENDING";
export const parsingStateParsed = "PARSED";
export const parsingStateReset = "RESET";

const initial_state = {
  trades: [],
  show_offer: false,
  parsing_state: parsingStateNone,
  parsed_offer: null,
  parsed_offer_name: "",
  pending_trades: [],
  trade_history: [],
  showing_trade: false,
  trade_showed: null
};

export const tradeReducer = (state = { ...initial_state }, action) => {
  let trade;
  switch (action.type) {
    case "INCOMING_MESSAGE":
      if (action.message.origin !== service_wallet) {
        return state;
      }

      const message = action.message;
      const data = message.data;
      const command = message.command;
      const success = data.success;

      if (command === "get_all_trades" && success === true) {
        const all_trades = data.trades;
        var pending_trades = [];
        var trade_history = [];
        for (var i = 0; i < all_trades.length; i++) {
          const trade = all_trades[i];
          const my_trade = trade.my_offer;
          const confirmed_at_index = trade.confirmed_at_index;
          if (my_trade === true && confirmed_at_index === 0) {
            pending_trades.push(trade);
          } else {
            trade_history.push(trade);
          }
        }
        return {
          ...state,
          trade_history: trade_history,
          pending_trades: pending_trades
        };
      }
      return state;
    case "LOG_OUT":
      return { ...initial_state };
    case "TRADE_ADDED":
      trade = action.trade;
      const new_trades = [...state.trades];
      new_trades.push(trade);
      return { ...state, trades: new_trades };
    case "RESET_TRADE":
      return { ...initial_state };
    case "OFFER_PARSING":
      var status = action.status;
      if (status === parsingStateParsed) {
        return {
          ...state,
          parsing_state: status,
          parsed_offer: action.offer,
          show_offer: true
        };
      } else if (status === parsingStateReset) {
        return {
          ...state,
          parsing_state: parsingStatePending,
          show_offer: false
        };
      }
      return {
        ...state,
        parsing_state: status
      };
    case "OFFER_NAME":
      return {
        ...state,
        parsed_offer_name: action.name,
        parsed_offer_path: action.path
      };
    case "PRESENT_OVERVIEW":
      return {
        ...state,
        showing_trade: false,
        trade_showed: null
      };
    case "PRESENT_TRADES":
      return {
        ...state,
        showing_trade: true,
        trade_showed: action.trade
      };
    default:
      return state;
  }
};
