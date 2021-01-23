const yaml = require('js-yaml');
const fs = require('fs');

let self_hostname = 'localhost';
let daemon_port = 55400;
let daemon_rpc_ws = `wss://${self_hostname}:${daemon_port}`;

const config_path = `C:\\Users\\dkack\\.chia\\beta-1.0b22\\config\\`;

function loadConfig() {
  try {
    const doc = yaml.load(fs.readFileSync(`${config_path}/config.yaml`, 'utf8'));

    self_hostname = doc.self_hostname;
    const daemon_port = doc.daemon_port;
    daemon_rpc_ws = `wss://${self_hostname}:${daemon_port}`;

    global.daemon_rpc_ws = daemon_rpc_ws;
    global.cert_path = `${config_path}/${doc.ssl.crt}`;
    global.key_path = `${config_path}/${doc.ssl.key}`;
  } catch (e) {
    console.log('Error loading config');
    console.log(e);    
  }
}

function manageDaemonLifetime() {
  return self_hostname === 'localhost';
}

module.exports = {
  loadConfig,
  manageDaemonLifetime,
  self_hostname,
  daemon_rpc_ws
};
