import { service_plotter } from "../util/service_names";
import { daemonMessage } from "./daemon_messages";

export const plotControl = () => ({
  type: "PLOTTER_CONTROL"
});

export const startPlotting = (size, count, workspace, final) => {
  var action = daemonMessage();
  action.message.command = "start_plotting";
  action.message.data = {
    service: service_plotter,
    k: size,
    n: count,
    t: workspace,
    t2: workspace,
    d: final
  };
  return action;
};

export const workspaceSelected = location => {
  const action = plotControl();
  action.command = "workplace_location";
  action.location = location;
  return action;
};

export const finalSelected = location => {
  const action = plotControl();
  action.command = "final_location";
  action.location = location;
  return action;
};

export const plottingStarted = () => {
  const action = plotControl();
  action.command = "plotting_started";
  action.started = true;
  return action;
};

export const plottingStopped = () => {
  const action = plotControl();
  action.command = "plotting_stopped";
  action.stopped = true;
  return action;
};

export const proggressLocation = location => {
  const action = plotControl();
  action.command = "progress_location";
  action.location = location;
  return action;
};

export const resetProgress = () => {
  const action = plotControl();
  action.command = "reset_progress";
  return action;
};

export const addProgress = progress => {
  const action = plotControl();
  action.command = "add_progress";
  action.progress = progress;
  return action;
};
