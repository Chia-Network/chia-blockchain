import Client from '../Client';
import Service from './Service';
import type { Options } from './Service';
import type Message from '../Message';
import ServiceName from '../constants/ServiceName';

export default class Plotter extends Service {
  constructor(client: Client, options?: Options) {
    super(ServiceName.PLOTTER, client, options);
  }

  async getPlots() {
    return this.command('get_plots');
  }

  async refreshPlots() {
    return this.command('refresh_plots');
  }

  onLogChanged(cb: (data: any, message: Message) => void) {
    return this.onStateChanged('log_changed', cb, (data) => data.queue);
  }
}
