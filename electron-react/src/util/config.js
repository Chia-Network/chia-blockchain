var self_hostname = "localhost";

const wallet_rpc_host_and_port = "ws://" + self_hostname + ":9256";
const full_node_rpc_host = self_hostname;
const full_node_rpc_port = 8555;

module.exports = {
  setSelfHostName: (hostname) => {
    self_hostname = hostname;
  },
  isLocalHost: () => {
    return self_hostname === "localhost";
  },
  getDaemonHost: () => {
    return "wss://" + self_hostname + ":55400";
  },
  self_hostname,
  wallet_rpc_host_and_port,
  full_node_rpc_host,
  full_node_rpc_port
};
