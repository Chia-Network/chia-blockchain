import Wallet from '../services/Wallet';

export default class CATWallet extends Wallet {
  async createNewWallet(
    amount: string, 
    fee: string, 
    host: string = this.client.backupHost,
  ) {
    return super.createNewWallet('cat_wallet', {
      mode: 'new',
      amount,
      fee,
      host,
    });
  }

  async createWalletForExisting(
    tail: string, 
    fee: string, 
    host: string = this.client.backupHost,
  ) {
    return super.createNewWallet('cat_wallet', {
      mode: 'existing',
      colour: tail,
      fee,
      host,
    });
  }

  async getTail(walletId: number) {
    return this.command('cc_get_colour', {
      walletId,
    });
  }

  async getName(walletId: number) {
    return this.command('cc_get_name', {
      walletId,
    });
  }

  async setName(walletId: number, name: string) {
    return this.command('cc_set_name', {
      walletId,
      name,
    });
  }

  async spend(walletId: number, innerAddress: string, amount: string, fee: string, memos?: string[]) {
    return this.command('cc_spend', {
      walletId,
      innerAddress,
      amount,
      fee,
      memos,
    });
  }

  async getCatList() {
    return this.command('get_cat_list');
  }
}
