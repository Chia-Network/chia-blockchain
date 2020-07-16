export const standardWallet = "STANDARD_WALLET";
export const createWallet = "CREATE_WALLET";
export const CCWallet = "CC_WALLET";
export const RLWallet = "RL_WALLET";

export const changeWalletMenu = (item, id) => ({
  type: "WALLET_MENU",
  item: item,
  id: id
});

const initial_state = {
  view: standardWallet,
  id: 1
};

export const walletMenuReducer = (state = { ...initial_state }, action) => {
  switch (action.type) {
    case "LOG_OUT":
      return { ...initial_state };
    case "WALLET_MENU":
      var item = action.item;
      var id = action.id;
      return { ...state, view: item, id: id };
    default:
      return state;
  }
};
