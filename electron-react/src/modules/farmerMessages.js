import { service_farmer } from "../util/service_names";

export const farmerMessage = () => ({
  type: "OUTGOING_MESSAGE",
  destination: service_farmer
});

export const pingFarmer = () => {
  var action = farmerMessage();
  action.command = "ping";
  action.data = {};
  return action;
};

export const getLatestChallenges = () => {
  var action = farmerMessage();
  action.command = "get_latest_challenges";
  action.data = {};
  return action;
};

export const getFarmerConnections = () => {
  var action = farmerMessage();
  action.command = "get_connections";
  action.data = {};
  return action;
};

export const openConnection = (host, port) => {
  var action = farmerMessage();
  action.command = "open_connection";
  action.data = { host, port };
  return action;
};

export const closeConnection = node_id => {
  var action = farmerMessage();
  action.command = "close_connection";
  action.data = { node_id };
  return action;
};
