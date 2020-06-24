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

export const PendingTrade = (trade_id, status, offer_dict, timestamp) => ({
  trade_id: trade_id,
  status: status,
  offer_dict: offer_dict,
  timestamp: timestamp
});

const now = Math.floor(Date.now() / 1000);
const example_trade = {
  trade_id: "ababebababa",
  status: "Pending",
  timestamp: now,
  offer_dict: { Chia: 100, sadasdas: 300, asdasda: -100 }
};

const initial_state = {
  trades: [],
  show_offer: false,
  parsing_state: parsingStateNone,
  parsed_offer: null,
  parsed_offer_name: "",
  pending_trades: [example_trade],
  trade_history: [],
  showing_trade: true,
  trade_showed: example_trade
};

export const tradeReducer = (state = { ...initial_state }, action) => {
  let trade;
  switch (action.type) {
    case "LOG_OUT":
      return { ...initial_state };
    case "TRADE_ADDED":
      trade = action.trade;
      const new_trades = [...state.trades];
      new_trades.push(trade);
      return { ...state, trades: new_trades };
    case "RESET_TRADE":
      state = { ...initial_state };
      return state;
    case "OFFER_PARSING":
      var status = action.status;
      state.parsing_state = status;
      if (status === parsingStateParsed) {
        state.parsed_offer = action.offer;
        state.show_offer = true;
      } else if (status === parsingStateReset) {
        state.show_offer = false;
        state.parsing_state = parsingStatePending;
      }
      return state;
    case "OFFER_NAME":
      state.parsed_offer_name = action.name;
      state.parsed_offer_path = action.path;
      return state;
    case "PRESENT_OVERVIEW":
      state.showing_trade = false;
      state.trade_showed = null;
      return state;
    case "PRESENT_TRADES":
      state.showing_trade = true;
      state.trade_showed = action.trade;
      return state;
    default:
      return state;
  }
};
