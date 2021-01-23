const yaml = require('js-yaml');
const fs = require('fs');
const semver = require('semver');
const homedir = require('os').homedir();

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
    if (sv.prerelease.length > 0) {
      version = `beta-${sv.major}.${sv.minor}${sv.prerelease[0]}`;
    }

    const config_path = `${homedir}/.chia/${version}/config`;
    const doc = yaml.load(fs.readFileSync(`${config_path}/config.yaml`, 'utf8'));

    self_hostname = doc.self_hostname;
    const daemon_port = doc.daemon_port;

    // store these in the global object so they can be used by both main and renderer processes
    global.daemon_rpc_ws = `wss://${self_hostname}:${daemon_port}`;
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
  self_hostname
};
