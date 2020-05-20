import { service_harvester } from "../util/service_names";

export const harvesterMessage = () => ({
  type: "OUTGOING_MESSAGE",
  destination: service_harvester
});

export const pingHarvester = () => {
  var action = harvesterMessage();
  action.command = "ping";
  action.data = {};
  return action;
};

export const getPlots = () => {
  var action = harvesterMessage();
  action.command = "get_plots";
  action.data = {};
  return action;
};

export const deletePlot = filename => {
  var action = harvesterMessage();
  action.command = "delete_plot";
  action.data = { filename };
  return action;
};

export const refreshPlots = () => {
  var action = harvesterMessage();
  action.command = "refresh_plots";
  action.data = {};
  return action;
};
