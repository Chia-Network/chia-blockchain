const yaml = require('js-yaml');
const fs = require('fs');
const semver = require('semver');
const os = require('os');
const path = require("path");

// defaults
let self_hostname = 'localhost';
global.daemon_rpc_ws = `wss://${self_hostname}:55400`;
global.cert_path = 'trusted.crt';
global.key_path = 'trusted.key';

function loadConfig() {
  try {
    // get the semver out of package.json and format for chia version approach
    const sv = semver.parse(require('../../package.json').version);
    let version = sv.version;

    // package major will be 0 until release
    if (sv.major == 0) {
      version = `beta-1.0b${sv.patch}`;
    }

    const config_dir = path.join(os.homedir(), '.chia', version, 'config');
    const config = yaml.load(fs.readFileSync(path.join(config_dir, 'config.yaml'), 'utf8'));

    self_hostname = typeof config.ui.daemon_host !== "undefined" ? config.ui.daemon_host : 'localhost';
    const daemon_port = typeof config.ui.daemon_port !== "undefined" ? config.ui.daemon_port : 55400;

    // store these in the global object so they can be used by both main and renderer processes
    global.daemon_rpc_ws = `wss://${self_hostname}:${daemon_port}`;
    global.cert_path = path.join(config_dir, config.ui.ssl.crt);
    global.key_path = path.join(config_dir, config.ui.ssl.key);
  } catch (e) {
    console.log('Error loading config');
    console.log(e);    
  }
}

function manageDaemonLifetime() {
  // only start/stop daemon if it is running locally
  return self_hostname === 'localhost';
}

module.exports = {
  loadConfig,
  manageDaemonLifetime,
  self_hostname
};
