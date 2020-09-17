import WalletType from "../types/WalletType";

export const standardWallet = "STANDARD_WALLET";
export const createWallet = "CREATE_WALLET";
export const CCWallet = "CC_WALLET";
export const RLWallet = "RL_WALLET";

export const changeWalletMenu = (item, id) => ({
  type: "WALLET_MENU",
  item: item,
  id: id
});

type WalletMenuState = {
  view: WalletType,
  id: number,
};

const initialState: WalletMenuState  = {
  view: WalletType.STANDARD_WALLET,
  id: 1
};

export default function walletMenuReducer(state = { ...initialState }, action: any): WalletMenuState {
  switch (action.type) {
    case "LOG_OUT":
      return { ...initialState };
    case "WALLET_MENU":
      var item = action.item;
      var id = action.id;
      return { ...state, view: item, id: id };
    default:
      return state;
  }
}
