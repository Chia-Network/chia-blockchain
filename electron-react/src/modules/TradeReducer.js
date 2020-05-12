export const addTrade = (trade) => ({ type: 'TRADE_ADDED', trade});
export const resetTrades = () => ({ type: 'RESET_TRADE'});

export const newBuy = (amount, id) => ({
    amount: amount,
    wallet_id: id,
    side: 'buy',
})

export const newSell = (amount, id) => ({
    amount: amount,
    wallet_id: id,
    side: 'sell',
})

const initial_state = { 
 trades: [],
};
  
  
export const tradeReducer = (state = { ...initial_state }, action) => {
switch (action.type) {
    case "TRADE_ADDED":
        var trade = action.trade
        const new_trades = [...state.trades]
        new_trades.push(trade)
        return {...state, trades: new_trades}
    case "RESET_TRADE":
        var trade = []
        state.trades = trade
        return state
    default:
    return state;
}
};
