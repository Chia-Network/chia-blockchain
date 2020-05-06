const initial_state = { mnemonic: [] };

export const incomingReducer = (state = { ...initial_state }, action) => {
  switch (action.type) {
    case "INCOMING_MESSAGE":
      if (action.command === "generate_mnemonic") {
        var mnemonic_data = action.data.mnemonic
        
        return { ...state, mnemonic: mnemonic_data};
      }
      break;
    default:
      return state;
  }
};
