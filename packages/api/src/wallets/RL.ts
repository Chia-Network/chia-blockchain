import Wallet from '../services/Wallet';

export default class RLWallet extends Wallet {
  async createAdminWallet(interval: string, limit: string, pubkey: string, amount: string, host: string = this.client.backupHost) {
    return this.createNewWallet('rl_wallet', {
      rlType: 'admin',
      interval,
      limit,
      pubkey,
      amount,
      host,
    });
  }

  async createUserWallet(host: string = this.client.backupHost) {
    return this.createNewWallet('rl_wallet', {
      rlType: 'user',
      host,
    });
  }

  async setUserInfo(
    walletId: number,
    interval: string,
    limit: string,
    origin: string,
    adminPubkey: string,
  ) {
    return this.command('rl_set_user_info', {
      walletId,
      interval,
      limit,
      origin,
      adminPubkey,
    });
  }

  async clawbackCoin(/* walletId: number */) {
    // THIS IS A PLACEHOLDER FOR RL CLAWBACK FUNCTIONALITY
    throw new Error('RL Clawback is not implemented');
  }
}
