import { service_full_node } from "../util/service_names";

export const fullNodeMessage = () => ({
  type: "OUTGOING_MESSAGE",
  destination: service_full_node
});

export const pingFullNode = () => {
  var action = fullNodeMessage();
  action.command = "ping";
  action.data = {};
  return action;
};

export const getBlockChainState = () => {
  var action = fullNodeMessage();
  action.command = "get_blockchain_state";
  action.data = {};
  return action;
};
