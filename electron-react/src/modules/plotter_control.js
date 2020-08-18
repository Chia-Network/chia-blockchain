const initial_state = {
  plotting_in_proggress: false,
  workspace_location: "",
  t2: "",
  final_location: "",
  progress_location: "",
  progress: "",
  plotting_stopped: false
};

export const plotControlReducer = (state = { ...initial_state }, action) => {
  switch (action.type) {
    case "LOG_OUT":
      return { ...initial_state };
    case "PLOTTER_CONTROL":
      if (action.command === "workplace_location") {
        return { ...state, workplace_location: action.location };
      } else if (action.command === "final_location") {
        return { ...state, final_location: action.location };
      } else if (action.command === "reset_progress") {
        return { ...state, progress: "" };
      } else if (action.command === "add_progress") {
        return { ...state, progress: state.progress + "\n" + action.progress };
      } else if (action.command === "plotting_started") {
        return {
          ...state,
          plotting_in_proggress: true,
          plotting_stopped: false
        };
      } else if (action.command === "progress_location") {
        return { ...state, progress_location: action.location };
      } else if (action.command === "plotting_stopped") {
        return { ...state, plotting_stopped: true };
      }
      return state;
    default:
      return state;
  }
};
