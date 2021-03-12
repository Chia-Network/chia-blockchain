import { service_farmer } from '../util/service_names';
import { async_api } from './message';

export const farmerMessage = (message) => ({
  type: 'OUTGOING_MESSAGE',
  message: {
    destination: service_farmer,
    ...message,
  },
});

export const getRewardTargets = (searchForPrivateKey) => {
  return async (dispatch) => {
    const { data } = await async_api(
      dispatch,
      farmerMessage({
        command: 'get_reward_targets',
        data: {
          search_for_private_key: searchForPrivateKey,
        },
      }),
      false,
    );

    return data;
  };
};

export const setRewardTargets = (farmerTarget, poolTarget) => {
  return async (dispatch) => {
    const response = await async_api(
      dispatch,
      farmerMessage({
        command: 'set_reward_targets',
        data: {
          farmer_target: farmerTarget,
          pool_target: poolTarget,
        },
      }),
      false,
    );

    return response;
  };
};

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
