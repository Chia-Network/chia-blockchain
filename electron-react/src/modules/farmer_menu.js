export const presentFarmer = "FARMER";
export const presentPlotter = "PLOTTER";
export const presentHarvester = "HARVESTER";

export const changeFarmerMenu = item => ({ type: "FARMER_MENU", item: item });

const initial_state = {
  view: presentFarmer
};

export const farmerMenuReducer = (state = { ...initial_state }, action) => {
  switch (action.type) {
    case "FARMER_MENU":
      var item = action.item;
      return { ...state, view: item };
    default:
      return state;
  }
};
