import Wallet from '../services/Wallet';

export default class PoolWallet extends Wallet {
  async createNewWallet(
    initialTargetState: Object,
    fee: string, 
    host: string = this.client.backupHost,
  ) {
    return super.createNewWallet('pool_wallet', {
      mode: 'new',
      fee,
      host,
      initialTargetState,
    });
  }
}
