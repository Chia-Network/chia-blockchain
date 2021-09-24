import Connection from '../Connection';
import Service from './Service';
import type { Options } from './Service';
import ServiceName from '../constants/ServiceName';

export default class Harvester extends Service {
  constructor(connection: Connection, options?: Options) {
    super(ServiceName.HARVESTER, connection, options);
  }

  // deprecated
  async getPlots() {
    console.log('WARNING: get_plots is deprecated use get_harvesters');
    return this.command('get_plots');
  }

  async refreshPlots() {
    return this.command('refresh_plots');
  }

  async getPlotDirectories() {
    return this.command('get_plot_directories');
  }

  async deletePlot(filename: string) {
    return this.command('delete_plot', { 
      filename,
    });
  }

  async addPlotDirectory(dirname: string) {
    return this.command('add_plot_directory', { 
      dirname,
    });
  }

  async removePlotDirectory(dirname: string) {
    return this.command('remove_plot_directory', { 
      dirname,
    });
  }
}
