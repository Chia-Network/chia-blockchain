import { service_farmer } from '../util/service_names';

export const farmerMessage = () => ({
  type: 'OUTGOING_MESSAGE',
  message: {
    destination: service_farmer,
  },
});

export const pingFarmer = () => {
  const action = farmerMessage();
  action.message.command = 'ping';
  action.message.data = {};
  return action;
};

export const getLatestChallenges = () => {
  const action = farmerMessage();
  action.message.command = 'get_signage_points';
  action.message.data = {};
  return action;
};

export const getFarmerConnections = () => {
  const action = farmerMessage();
  action.message.command = 'get_connections';
  action.message.data = {};
  return action;
};

export const openConnection = (host, port) => {
  const action = farmerMessage();
  action.message.command = 'open_connection';
  action.message.data = { host, port };
  return action;
};

export const closeConnection = (node_id) => {
  const action = farmerMessage();
  action.message.command = 'close_connection';
  action.message.data = { node_id };
  return action;
};
