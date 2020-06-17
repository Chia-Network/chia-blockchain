export const tradingOverview = "TRADING_OVERVIEW";
export const createTrades = "CREATE_TRADE";
export const viewTrades = "VIEW_TRADE";

export const changeTradeMenu = (item, id) => ({
  type: "TRADE_MENU",
  item: item
});

const initial_state = {
  view: tradingOverview
};

export const tradeMenuReducer = (state = { ...initial_state }, action) => {
  switch (action.type) {
    case "TRADE_MENU":
      var item = action.item;
      var id = action.id;
      return { ...state, view: item, id: id };
    default:
      return state;
  }
};
