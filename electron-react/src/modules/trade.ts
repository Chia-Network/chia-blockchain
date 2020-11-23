import { service_wallet } from '../util/service_names';

export const addTrade = (trade: any) => ({ type: 'TRADE_ADDED', trade });
export const resetTrades = () => ({ type: 'RESET_TRADE' });
export const presentTrade = (trade: any) => ({ type: 'PRESENT_TRADES', trade });
export const presetOverview = () => ({ type: 'PRESENT_OVERVIEW' });

export const parsingStateNone = 'NONE';
export const parsingStatePending = 'PENDING';
export const parsingStateParsed = 'PARSED';
export const parsingStateReset = 'RESET';

export const newBuy = (amount: number, id: number) => ({
  amount,
  wallet_id: id,
  side: 'buy',
});

export const newSell = (amount: number, id: number) => ({
  amount,
  wallet_id: id,
  side: 'sell',
});

export const offerParsed = (offer: any) => ({
  type: 'OFFER_PARSING',
  status: parsingStateParsed,
  offer,
});
export const offerParsingName = (name: string, path: string) => ({
  type: 'OFFER_NAME',
  name,
  path,
});
export const parsingStarted = () => ({
  type: 'OFFER_PARSING',
  status: parsingStatePending,
});

type TradeState = {
  trades: any[];
  show_offer: boolean;
  parsing_state: 'NONE' | 'PENDING' | 'PARSED' | 'RESET';
  parsed_offer: any;
  parsed_offer_name: string;
  parsed_offer_path: string;
  pending_trades: Object[];
  trade_history: Object[];
  showing_trade: boolean;
  trade_showed?: boolean | null;
};

const initialState: TradeState = {
  trades: [],
  show_offer: false,
  parsing_state: parsingStateNone,
  parsed_offer: null,
  parsed_offer_name: '',
  parsed_offer_path: '',
  pending_trades: [],
  trade_history: [],
  showing_trade: false,
  trade_showed: null,
};

export default function tradeReducer(
  state = { ...initialState },
  action: any,
): TradeState {
  let trade;
  switch (action.type) {
    case 'INCOMING_MESSAGE':
      if (action.message.origin !== service_wallet) {
        return state;
      }

      const { message } = action;
      const { data } = message;
      const { command } = message;
      const { success } = data;

      if (command === 'get_all_trades' && success === true) {
        const all_trades = data.trades;
        const pending_trades: any[] = [];
        const trade_history: any[] = [];
        all_trades.forEach((trade: any) => {
          const my_trade = trade.my_offer;
          const { confirmed_at_index } = trade;
          if (my_trade === true && confirmed_at_index === 0) {
            pending_trades.push(trade);
          } else {
            trade_history.push(trade);
          }
        });

        return {
          ...state,
          trade_history,
          pending_trades,
        };
      }
      return state;
    case 'LOG_OUT':
      return { ...initialState };
    case 'TRADE_ADDED':
      trade = action.trade;
      const new_trades = [...state.trades];
      new_trades.push(trade);
      return { ...state, trades: new_trades };
    case 'RESET_TRADE':
      return { ...initialState };
    case 'OFFER_PARSING':
      const { status } = action;
      if (status === parsingStateParsed) {
        return {
          ...state,
          parsing_state: status,
          parsed_offer: action.offer,
          show_offer: true,
        };
      }
      if (status === parsingStateReset) {
        return {
          ...state,
          parsing_state: parsingStatePending,
          show_offer: false,
        };
      }
      return {
        ...state,
        parsing_state: status,
      };
    case 'OFFER_NAME':
      return {
        ...state,
        parsed_offer_name: action.name,
        parsed_offer_path: action.path,
      };
    case 'PRESENT_OVERVIEW':
      return {
        ...state,
        showing_trade: false,
        trade_showed: null,
      };
    case 'PRESENT_TRADES':
      return {
        ...state,
        showing_trade: true,
        trade_showed: action.trade,
      };
    default:
      return state;
  }
}
