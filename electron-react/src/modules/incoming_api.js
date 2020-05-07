
const initial_state = { mnemonic: [], logged_in: false };

export const incomingReducer = (state = { ...initial_state }, action) => {
  switch (action.type) {
    case "INCOMING_MESSAGE":
      if (action.command === "generate_mnemonic") {
        var mnemonic_data = action.data.mnemonic
        return { ...state, mnemonic: mnemonic_data};
      }
      if (action.command === "log_in") {
        var success = action.data.success 
        return {...state, logged_in: success}
      }
      if (action.command === "log_out") {
        var success = action.data.success 
        if (success) { 
          return {...state, logged_in: false}
        }
      }
      if (action.command === "logged_in") {
        var logged_in = action.data.logged_in
        return {...state, logged_in: logged_in}
      }
      if (action.command === "start_server") {
        var started = action.data.success
        return {...state, server_started: started}
      }
      return state
      break;
    default:
      return state;
  }
};
