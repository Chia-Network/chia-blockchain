
export const presentWallet = "WALLET"
export const presentNode = "NODE"
export const presentFarmer = "FARMER"
export const presentTimelord = "TIMELORD"

  export const changeView = (view, item) => ({ type: 'PRESENTER', view: view, item: item});
  
  const initial_state = { 
    main_menu: presentWallet
  };
  
  
  export const presenterReducer = (state = { ...initial_state }, action) => {
    switch (action.type) {
      case "PRESENTER":
        if (action.view === "main_menu") {
          var item = action.item
          return { ...state, main_menu: item};
        }
        return state
        break;
      default:
        return state;
    }
  };
  