import { get } from 'lodash';
import { readConfigFile } from './loadConfig';

export default function manageDaemonLifetime(net?: string): boolean {
  try {
    const config = readConfigFile(net);
    const selfHostname = get(config, 'ui.daemon_host', 'localhost');

    return selfHostname === 'localhost';
  } catch (error: any) {
    if (error.code === 'ENOENT') {
      // configuration file does not exists, use default value
      return true;
    } else {
      throw error;
    }
  }
}
