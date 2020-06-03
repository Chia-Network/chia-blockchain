const initial_state = {
  plotting_in_proggress: false,
  workspace_location: "",
  final_location: "",
  progress_location: "",
  progress: ""
};

export const plotControlReducer = (state = { ...initial_state }, action) => {
  switch (action.type) {
    case "LOG_OUT":
      return { ...initial_state };
    case "PLOTTER_CONTROL":
      if (action.command === "workplace_location") {
        state.workspace_location = action.location;
      } else if (action.command === "final_location") {
        state.final_location = action.location;
      } else if (action.command === "reset_progress") {
        state.progress = "";
      } else if (action.command === "add_progress") {
        state.progress += "\n" + action.progress;
      } else if (action.command === "plotting_started") {
        state.plotting_in_proggress = true;
      } else if (action.command === "progress_location") {
        state.progress_location = action.location;
      } else if (action.command === "plotting_stopped") {
        state.plotting_in_proggress = false;
        state.progress = "";
      }
      return state;
    default:
      return state;
  }
};
