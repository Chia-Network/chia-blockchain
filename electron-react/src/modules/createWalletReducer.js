export const CREATE_CC_WALLET_OPTIONS = "CREATE_CC_WALLET_OPTIONS";
export const CREATE_NEW_CC = "CREATE_NEW_CC";
export const CREATE_EXISTING_CC = "CREATE_EXISTING_CC";
export const CREATE_RL_WALLET_OPTIONS = "CREATE_RL_WALLET_OPTIONS";
export const CREATE_RL_ADMIN = "CREATE_RL_ADMIN";
export const CREATE_RL_USER = "CREATE_RL_USER";
export const ALL_OPTIONS = "ALL_OPTIONS";

export const changeCreateWallet = item => ({
  type: "CREATE_OPTIONS",
  item: item
});
export const createState = (created, pending) => ({
  type: "CREATE_STATE",
  created: created,
  pending: pending
});

const initial_state = {
  view: ALL_OPTIONS,
  created: false,
  pending: false
};

export const createWalletReducer = (state = { ...initial_state }, action) => {
  switch (action.type) {
    case "LOG_OUT":
      return { ...initial_state };
    case "CREATE_OPTIONS":
      var item = action.item;
      return { ...state, view: item };
    case "CREATE_STATE":
      const created = action.created;
      const pending = action.pending;
      return { ...state, created: created, pending: pending };
    default:
      return state;
  }
};
