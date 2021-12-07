const yaml = require('js-yaml');
const fs = require('fs');
const os = require('os');
const path = require('path');
const lodash = require('lodash');
const sleepModule = require('./sleep');

const sleep = lodash.default;

// defaults used in case of error point to the localhost daemon & its certs
let self_hostname = 'localhost';

async function loadConfig(net) {
  try {
    // check if CHIA_ROOT is set. it overrides 'net'
    const config_root_dir =
      'CHIA_ROOT' in process.env
        ? process.env.CHIA_ROOT
        : path.join(os.homedir(), '.chia', net);
    const config = yaml.load(
      fs.readFileSync(path.join(config_root_dir, 'config/config.yaml'), 'utf8'),
    );

    self_hostname = lodash.get(config, 'ui.daemon_host', 'localhost'); // jshint ignore:line
    const daemon_port = lodash.get(config, 'ui.daemon_port', 55401); // jshint ignore:line

    // store these in the global object so they can be used by both main and renderer processes
    global.daemon_rpc_ws = `wss://${self_hostname}:${daemon_port}`;
    global.cert_path = path.join(
      config_root_dir,
      lodash.get(
        config,
        'ui.daemon_ssl.private_crt',
        'config/ssl/daemon/private_daemon.crt',
      ),
    ); // jshint ignore:line
    global.key_path = path.join(
      config_root_dir,
      lodash.get(
        config,
        'ui.daemon_ssl.private_key',
        'config/ssl/daemon/private_daemon.key',
      ),
    ); // jshint ignore:line

    return {
      url: global.daemon_rpc_ws,
      cert: fs.readFileSync(global.cert_path).toString(),
      key: fs.readFileSync(global.key_path).toString(),
    };
  } catch (e) {
    if (e.code === 'ENOENT') {
      console.log('Waiting for configuration file');
      await sleep(1000);
      return loadConfig(net);
    } else {
      throw e;
    }
  }
}

function manageDaemonLifetime() {
  // only start/stop daemon if it is running locally
  return self_hostname === 'localhost';
}

module.exports = {
  loadConfig,
  manageDaemonLifetime,
  self_hostname,
};
