export const presentEntrace = "ENTRANCE";
export const presentNewWallet = "NEW_WALLET";
export const presentOldWallet = "OLD_WALLET";
export const presentDashboard = "DASHBOARD";
export const presentSelectKeys = "SELECT_KEYS";

export const changeEntranceMenu = item => ({
  type: "ENTRANCE_MENU",
  item: item
});

const initial_state = {
  view: presentEntrace
};

export const entranceReducer = (state = { ...initial_state }, action) => {
  switch (action.type) {
    case "ENTRANCE_MENU":
      var item = action.item;
      return { ...state, view: item };
    default:
      return state;
  }
};
