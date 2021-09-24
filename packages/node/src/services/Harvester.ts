import Connection from '../Connection';
import Service from './Service';
import type { Options } from './Service';
import ServiceName from '../constants/ServiceName';

export default class Harvester extends Service {
  constructor(connection: Connection, options?: Options) {
    super(ServiceName.HARVESTER, connection, options);
  }

  async getPlots() {
    return this.command('get_plots');
  }

  async refreshPlots() {
    return this.command('refresh_plots');
  }
}
