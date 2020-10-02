var self_hostname = "localhost";

const wallet_rpc_host_and_port = "ws://" + self_hostname + ":9256";
const full_node_rpc_host = self_hostname;
const full_node_rpc_port = 8555;
const default_daemon_host = "ws://localhost:55400";

module.exports = {
  self_hostname,
  wallet_rpc_host_and_port,
  full_node_rpc_host,
  full_node_rpc_port,
  default_daemon_host
};
