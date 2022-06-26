import Wallet from '../services/Wallet';

export default class NFTWallet extends Wallet {
  async getNfts(walletId: number) {
    return this.command('nft_get_nfts', {
      walletId,
    });
  }

  async getNftInfo(coinId: string) {
    return this.command('nft_get_info', {
      coinId,
    });
  }

  async getNftWalletsWithDids() {
    return this.command('nft_get_wallets_with_dids');
  }

  async transferNft(
    walletId: number,
    nftCoinId: string,
    targetAddress: string,
    fee: string
  ) {
    return this.command('nft_transfer_nft', {
      walletId,
      nftCoinId,
      targetAddress,
      fee,
    });
  }

  async setNftDid(
    walletId: number,
    nftCoinId: string,
    did: string,
    fee: string
  ) {
    return this.command('nft_set_nft_did', {
      walletId,
      nftCoinId,
      didId: did,
      fee,
    });
  }

  async setNftStatus(
    walletId: number,
    nftCoinId: string,
    inTransaction: boolean
  ) {
    return this.command('nft_set_nft_status', {
      walletId,
      coinId: nftCoinId,
      inTransaction,
    });
  }

  async receiveNft(walletId: number, spendBundle: any, fee: number) {
    return this.command('nft_receive_nft', {
      walletId,
      spendBundle,
      fee,
    });
  }
}
