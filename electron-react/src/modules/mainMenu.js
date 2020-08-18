export const presentWallet = "WALLET";
export const presentNode = "NODE";
export const presentFarmer = "FARMER";
export const presentPlotter = "PLOTTER";
export const presentTrading = "TRADING";

export const changeMainMenu = item => ({ type: "MAIN_MENU", item: item });

const initial_state = {
  view: presentWallet
};

export const mainMenuReducer = (state = { ...initial_state }, action) => {
  switch (action.type) {
    case "LOG_OUT":
      return { ...initial_state };
    case "MAIN_MENU":
      var item = action.item;
      return { ...state, view: item };
    default:
      return state;
  }
};
