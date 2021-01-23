const self_hostname = 'farmer';
const daemon_rpc_ws = `wss://${self_hostname}:55400`;

module.exports = {
  self_hostname,
  daemon_rpc_ws
};
