import { service_plotter } from '../util/service_names';
import { daemonMessage } from './daemon_messages';

export const plotControl = () => ({
  type: 'PLOTTER_CONTROL',
});

export const stopPlotting = (id) => {
  const action = daemonMessage();
  action.message.command = 'stop_plotting';
  action.message.data = {
    service: service_plotter,
    id,
  };

  return action;
};

export const startPlotting = (
  k,
  n,
  t,
  t2,
  d,
  b,
  u,
  r,
  queue,
  a,
  parallel,
  delay,
  e,
  x,
  overrideK,
) => {
  const action = daemonMessage();
  action.message.command = 'start_plotting';

  const data = {
    service: service_plotter,
    k,
    n,
    t,
    t2,
    d,
    b,
    u,
    r,
    queue,
    parallel,
    delay,
    e,
    x,
    overrideK,
  };

  if (a) {
    data.a = a;
  }

  action.message.data = data;

  return action;
};

/*
export const workspaceSelected = (location) => {
  const action = plotControl();
  action.command = 'workspace_location';
  action.location = location;
  return action;
};

export const finalSelected = (location) => {
  const action = plotControl();
  action.command = 'final_location';
  action.location = location;
  return action;
};
*/

export const plottingStarted = () => {
  const action = plotControl();
  action.command = 'plotting_started';
  action.started = true;
  return action;
};

export const plottingStopped = () => {
  const action = plotControl();
  action.command = 'plotting_stopped';
  action.stopped = true;
  return action;
};

export const proggressLocation = (location) => {
  const action = plotControl();
  action.command = 'progress_location';
  action.location = location;
  return action;
};

export const resetProgress = () => {
  const action = plotControl();
  action.command = 'reset_progress';
  return action;
};

export const addProgress = (progress) => {
  const action = plotControl();
  action.command = 'add_progress';
  action.progress = progress;
  return action;
};
