const initial_state = {};

export const farmerMenuReducer = (state = { ...initial_state }, action) => {
  switch (action.type) {
    case "LOG_OUT":
      return { ...initial_state };
    default:
      return state;
  }
};
