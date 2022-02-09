import Client from '../Client';
import Service from './Service';
import type { Options } from './Service';
import ServiceName from '../constants/ServiceName';
import type Message from '../Message';

export default class Wallet extends Service {
  constructor(client: Client, options?: Options) {
    super(ServiceName.WALLET, client, options);
  }

  async getLoggedInFingerprint() {
    return this.command('get_logged_in_fingerprint');
  }

  async getWallets() {
    return this.command('get_wallets');
  }

  async getTransaction(transactionId: string) {
    return this.command('get_transaction', {
      transactionId,
    });
  }

  async getPwStatus(walletId: number) {
    return this.command('pw_status', {
      walletId,
    });
  }

  async pwAbsorbRewards(walletId: number, fee?: string) {
    return this.command('pw_absorb_rewards', {
      walletId,
      fee,
    });
  }

  async pwJoinPool(
    walletId: number,
    poolUrl: string,
    relativeLockHeight: number,
    targetPuzzlehash?: string,
    fee?: string,
  ) {
    return this.command('pw_join_pool', {
      walletId,
      poolUrl,
      relativeLockHeight,
      targetPuzzlehash,
      fee,
    });
  }

  async pwSelfPool(walletId: number, fee?: string) {
    return this.command('pw_self_pool', {
      walletId,
      fee,
    });
  }

  async createNewWallet(
    walletType: 'pool_wallet' | 'rl_wallet' | 'did_wallet' | 'cat_wallet',
    options: Object = {},
  ) {
    return this.command('create_new_wallet', {
      host: this.client.backupHost,
      walletType,
      ...options,
    });
  }

  async deleteUnconfirmedTransactions(walletId: number) {
    return this.command('delete_unconfirmed_transactions', {
      walletId,
    });
  }

  async getWalletBalance(walletId: number) {
    return this.command('get_wallet_balance', {
      walletId,
    });
  }

  async getFarmedAmount() {
    return this.command('get_farmed_amount');
  }

  async sendTransaction(walletId: number, amount: string, fee: string, address: string) {
    return this.command('send_transaction', {
      walletId,
      amount,
      fee,
      address,
    });
  }

  async generateMnemonic(): Promise<{
    mnemonic: string[];
    success: boolean;
  }> {
    return this.command('generate_mnemonic');
  }

  async getPublicKeys(): Promise<{
    publicKeyFingerprints: number[];
    success: boolean;
  }> {
    return this.command('get_public_keys');
  }

  async addKey(
    mnemonic: string[], 
    type: 'new_wallet' | 'skip' | 'restore_backup', 
    filePath?: string,
  ) {
    return this.command('add_key', {
      mnemonic,
      type,
      filePath,
    });
  }

  async deleteKey(fingerprint: string) {
    return this.command('delete_key', {
      fingerprint,
    });
  }

  async checkDeleteKey(fingerprint: string) {
    return this.command('check_delete_key', {
      fingerprint,
    });
  }

  async deleteAllKeys() {
    return this.command('delete_all_keys');
  }

  async logIn(
    fingerprint: string, 
    type: 'normal' | 'skip' | 'restore_backup' = 'normal', // skip is used to skip import
    host: string = this.client.backupHost,
    filePath?: string,
  ) {
    return this.command('log_in', {
      fingerprint,
      type,
      filePath,
      host,
    });
  }

  logInAndSkipImport(
    fingerprint: string,
    host: string = this.client.backupHost,
  ) {
    return this.logIn(fingerprint, 'skip', host);
  }

  logInAndImportBackup(
    fingerprint: string,
    filePath: string,
    host: string = this.client.backupHost,
  ) {
    return this.logIn(fingerprint, 'restore_backup', host, filePath);
  }

  async getBackupInfo(
    filePath: string, 
    options: { fingerprint: string } | { words: string },
  ) {
    return this.command('get_backup_info', {
      filePath,
      ...options,
    });
  }

  async getBackupInfoByFingerprint(filePath: string, fingerprint: string) {
    return this.getBackupInfo(filePath, {
      fingerprint,
    });
  }

  async getBackupInfoByWords(filePath: string, words: string) {
    return this.getBackupInfo(filePath, {
      words,
    });
  }

  async getPrivateKey(fingerprint: string) {
    return this.command('get_private_key', {
      fingerprint,
    });
  }

  async getTransactions(walletId: number, start?: number, end?: number, sortKey?: 'CONFIRMED_AT_HEIGHT' | 'RELEVANCE', reverse?: boolean) {
    return this.command('get_transactions', {
      walletId,
      start,
      end,
      sortKey,
      reverse,
    });
  }

  async getTransactionsCount(walletId: number) {
    return this.command('get_transaction_count', {
      walletId,
    });
  }

  async getNextAddress(walletId: number, newAddress: boolean) {
    return this.command('get_next_address', {
      walletId,
      newAddress,
    });
  }

  async farmBlock(address: string) {
    return this.command('farm_block', {
      address,
    });
  }

  async getHeightInfo() {
    return this.command('get_height_info');
  }

  async getNetworkInfo() {
    return this.command('get_network_info');
  }

  async getSyncStatus() {
    return this.command('get_sync_status');
  }

  async getConnections() {
    return this.command('get_connections');
  }

  async createBackup(filePath: string) {
    return this.command('create_backup', {
      filePath,
    });
  }

  async getAllOffers(
    start?: number,
    end?: number,
    sortKey?: 'CONFIRMED_AT_HEIGHT' | 'RELEVANCE',
    reverse?: boolean,
    includeMyOffers?: boolean,
    includeTakenOffers?: boolean) {
    return this.command('get_all_offers', {
      include_completed: true,
      file_contents: true,
      start,
      end,
      sortKey,
      reverse,
      excludeMyOffers: includeMyOffers ? false : true,
      excludeTakenOffers: includeTakenOffers ? false : true,
    });
  }

  async getOffersCount() {
    return this.command('get_offers_count', {
    });
  }

  async createOfferForIds(walletIdsAndAmounts: { [key: string]: number }, validateOnly?: boolean) {
    return this.command('create_offer_for_ids', {
      offer: walletIdsAndAmounts,
      validate_only: validateOnly || false,
    });
  }

  async cancelOffer(tradeId: string, secure: boolean, fee: number | string) {
    return this.command('cancel_offer', {
      trade_id: tradeId,
      secure,
      fee,
    });
  }

  async checkOfferValidity(offer: string) {
    return this.command('check_offer_validity', {
      offer,
    });
  }

  async takeOffer(offer: string, fee: number | string) {
    return this.command('take_offer', {
      offer,
      fee,
    });
  }

  async getOfferSummary(offerData: string) {
    return this.command('get_offer_summary', {
      offer: offerData,
    });
  }

  async getOfferData(offerId: string) {
    return this.command('get_offer', {
      trade_id: offerId,
      file_contents: true,
    });
  }

  async getOfferRecord(offerId: string) {
    return this.command('get_offer', {
      trade_id: offerId,
      file_contents: false,
    });
  }

  onSyncChanged(callback: (data: any, message: Message) => void) {
    return this.onStateChanged('sync_changed', callback);
  }

  onNewBlock(callback: (data: any, message: Message) => void) {
    return this.onStateChanged('new_block', callback);
  }

  onNewPeak(callback: (data: any, message: Message) => void) {
    return this.onStateChanged('new_peak', callback);
  }

  onCoinAdded(callback: (
    data: {
      additionalData: Object;
      state: 'coin_added';
      success: boolean;
      walletId: number;
    }, 
    message: Message,
  ) => void) {
    return this.onStateChanged('coin_added', callback);
  }

  onCoinRemoved(callback: (
    data: {
      additionalData: Object;
      state: "coin_removed"
      success: boolean;
      walletId: number;
    }, 
    message: Message,
  ) => void) {
    return this.onStateChanged('coin_removed', callback);
  }

  onWalletCreated(
    callback: (data: any, message: Message) => void,
    processData?: (data: any) => any,
  ) {
    return this.onStateChanged('wallet_created', callback, processData);
  }

  onConnections(
    callback: (data: any, message: Message) => void,
    processData?: (data: any) => any,
  ) {
    return this.onCommand('get_connections', callback, processData);
  }

  onTransactionUpdate(
    callback: (data: any, message: Message) => void,
    processData?: (data: any) => any,
  ) {
    return this.onStateChanged('tx_update', callback, processData);
  }

  onPendingTransaction(
    callback: (data: any, message: Message) => void,
    processData?: (data: any) => any,
  ) {
    return this.onStateChanged('pending_transaction', callback, processData);
  }

  onOfferAdded(
    callback: (data: any, message: Message) => void) {
    return this.onStateChanged('offer_added', callback);
  }

  onOfferUpdated(
    callback: (data: any, message: Message) => void) {
    return this.onStateChanged('offer_cancelled', callback);
  }
}
