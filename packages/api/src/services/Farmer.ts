import Client from '../Client';
import Service from './Service';
import type { Options } from './Service';
import type FarmingInfo from '../@types/FarmingInfo';
import type Message from '../Message';
import ServiceName from '../constants/ServiceName';

const FARMING_INFO_MAX_ITEMS = 1000;
export default class Farmer extends Service {
  // last FARMING_INFO_MAX_ITEMS farming info
  private farmingInfo: FarmingInfo[] = [];

  constructor(client: Client, options?: Options) {
    super(ServiceName.FARMER, client, options, async () => {
      this.onNewFarmingInfo((data) => {
        const { farmingInfo } = data;

        if (farmingInfo) {
          this.farmingInfo = [
            farmingInfo,
            ...this.farmingInfo,
          ].slice(0, FARMING_INFO_MAX_ITEMS);

          this.emit('farming_info_changed', this.farmingInfo, null);
        }
      });
    });
  }

  async getFarmingInfo() {
    await this.whenReady();
    return this.farmingInfo;
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

  onNewPlots(
    callback: (data: any, message: Message) => void,
    processData?: (data: any) => any,
  ) {
    return this.onCommand('new_plots', callback, processData);
  }

  onNewSignagePoint(
    callback: (data: any, message: Message) => void,
    processData?: (data: any) => any,
  ) {
    return this.onCommand('new_signage_point', callback, processData);
  }

  onHarvesterChanged(
    callback: (data: any, message: Message) => void,
    processData?: (data: any) => any,
  ) {
    return this.onCommand('get_harvesters', callback, processData);
  }

  onRefreshPlots(
    callback: (data: any, message: Message) => void,
    processData?: (data: any) => any,
  ) {
    return this.onCommand('refresh_plots', callback, processData);
  }

  onFarmingInfoChanged(
    callback: (data: any, message?: Message) => void,
    processData?: (data: any) => any,
  ) {
    return this.onCommand('farming_info_changed', callback, processData);
  }
}
