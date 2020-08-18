const progressControl = () => ({ type: "PROGRESS_CONTROL" });

export const openProgress = () => {
  var action = progressControl();
  action.open = true;
  return action;
};

export const closeProgress = id => {
  var action = progressControl();
  action.open = false;
  return action;
};

const initial_state = {
  progress_indicator: false
};

export const progressReducer = (state = { ...initial_state }, action) => {
  switch (action.type) {
    case "PROGRESS_CONTROL":
      return { ...state, progress_indicator: action.open };
    default:
      return state;
  }
};
