import Client from '../Client';
import Service from './Service';
import type { Options } from './Service';
import type Message from '../Message';
import ServiceName from '../constants/ServiceName';

export default class Farmer extends Service {
  constructor(client: Client, options?: Options) {
    super(ServiceName.FARMER, client, options);
  }

  async getRewardTargets(searchForPrivateKey: boolean) {
    return this.command('get_reward_targets', {
      searchForPrivateKey,
    });
  }

  async setRewardTargets(farmerTarget: string, poolTarget: string) {
    return this.command('set_reward_targets', {
      farmerTarget,
      poolTarget,
    });
  }

  async getSignagePoints() {
    return this.command('get_signage_points');
  }

  async getConnections() {
    return this.command('get_connections');
  }

  async openConnection(host: string, port: string) {
    return this.command('open_connection', {
      host,
      port,
    });
  }

  async closeConnection(nodeId: string) {
    return this.command('close_connection', {
      nodeId,
    });
  }

  async getPoolState() {
    return this.command('get_pool_state');
  }

  async setPayoutInstructions(launcherId: string, payoutInstructions: string) {
    return this.command('set_payout_instructions', {
      launcherId,
      payoutInstructions,
    });
  }

  async getHarvesters() {
    return this.command('get_harvesters');
  }

  async getPoolLoginLink(launcherId: string) {
    return this.command('get_pool_login_link', {
      launcherId,
    });
  }

  onNewFarmingInfo(
    callback: (data: any, message: Message) => void,
    processData?: (data: any) => any,
  ) {
    return this.onCommand('new_farming_info', callback, processData);
  }

  onNewSignagePoint(
    callback: (data: any, message: Message) => void,
    processData?: (data: any) => any,
  ) {
    return this.onCommand('new_signage_point', callback, processData);
  }

  onRefreshPlots(
    callback: (data: any, message: Message) => void,
    processData?: (data: any) => any,
  ) {
    return this.onCommand('refresh_plots', (...args) => {
      console.log('refresh_plots in farmer', ...args);
      return callback(...args);
    }, processData);
  }
}
