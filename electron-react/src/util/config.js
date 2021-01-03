const self_hostname = 'localhost';
const daemon_rpc_ws = `wss://${self_hostname}:55400`;
const wallet_rpc_host_and_port = `ws://${self_hostname}:9256`;
const full_node_rpc_host = self_hostname;
const full_node_rpc_port = 8555;

module.exports = {
  self_hostname,
  daemon_rpc_ws,
  wallet_rpc_host_and_port,
  full_node_rpc_host,
  full_node_rpc_port,
};
