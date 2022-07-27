import Wallet from '../services/Wallet';

export default class DIDWallet extends Wallet {
  async createNewWallet(
    amount: string,
    fee: string,
    backupDids: string,
    numOfBackupIdsNeeded: number,
    host: string = this.client.backupHost,
  ) {
    return super.createNewWallet('did_wallet', {
      did_type: 'new',
      amount,
      fee,
      backupDids,
      numOfBackupIdsNeeded,
      host,
    });
  }

  async createNewRecoveryWallet(filename: string, host: string = this.client.backupHost) {
    return super.createNewWallet('did_wallet', {
      did_type: 'recovery',
      filename,
      host,
    });
  }

  async updateRecoveryIds(walletId: number, newList: string[], numVerificationsRequired: boolean) {
    return this.command('did_update_recovery_ids', {
      walletId,
      newList,
      numVerificationsRequired,
    });
  }

  async getPubKey(walletId: number) {
    return this.command('did_get_pubkey', {
      walletId,
    });
  }

  async spend(walletId: number, puzzlehash: string) {
    return this.command('did_spend', {
      walletId,
      puzzlehash,
    });
  }

  async getDid(walletId: number) {
    return this.command('did_get_did', {
      walletId,
    });
  }

  async getDidName(walletId: number) {
    return this.command('did_get_wallet_name', {
      walletId,
    });
  }

  async setDIDName(walletId: number, name: string) {
    return this.command('did_set_wallet_name', {
      walletId,
      name,
    });
  }

  async getRecoveryList(walletId: number) {
    return this.command('did_get_recovery_list', {
      walletId,
    });
  }

  async recoverySpend(walletId: number, attestFilenames: string[]) {
    return this.command('did_recovery_spend', {
      walletId,
      attestFilenames,
    });
  }

  async createAttest(walletId: number, filename: string, coinName: string, pubkey: string, puzhash: string) {
    return this.command('did_create_attest', {
      walletId,
      filename,
      coinName,
      pubkey,
      puzhash,
    });
  }

  async createBackupFile(walletId: number, filename: string) {
    return this.command('did_create_backup_file', {
      walletId,
      filename,
    });
  }

  async getInformationNeededForRecovery(walletId: number) {
    return this.command('did_get_information_needed_for_recovery', {
      walletId,
    });
  }

  async getCurrentCoinInfo(walletId: number) {
    return this.command('did_get_current_coin_info', {
      walletId,
    });
  }

  onDIDCoinAdded(callback: (data: any, message: Message) => void) {
    return this.onStateChanged('did_coin_added', callback);
  }
}
