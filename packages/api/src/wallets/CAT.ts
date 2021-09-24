import Wallet from '../services/Wallet';

export default class CATWallet extends Wallet {
  async createNewWallet(amount: string, fee: string, host?: string) {
    return super.createNewWallet('cc_wallet', {
      mode: 'new',
      amount,
      fee,
      host,
    });
  }

  async createWalletForExisting(colour: string, fee: string, host?: string) {
    return super.createNewWallet('cc_wallet', {
      mode: 'existing',
      colour,
      fee,
      host,
    });
  }

  async getColour(walletId: number) {
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

  async spend(walletId: number, innerAddress: string, amount: string, fee: string) {
    return this.command('cc_spend', {
      walletId,
      innerAddress,
      amount,
      fee,
    });
  }
}
