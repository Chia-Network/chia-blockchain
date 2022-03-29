import Wallet from '../services/Wallet';

export default class DIDWallet extends Wallet {
  async getCurrentNfts(walletId: number) {
    return this.command('nft_get_current_nfts', {
      walletId,
    });
  }

  async transferNft(
    walletId: number,
    nftCoinInfo: any,
    newDid: string,
    newDidParent: string,
    newDidInnerHash: string,
    newDidAmount: number,
    tradePrice: number) {
    return this.command('nft_transfer_nft', {
      walletId,
      nftCoinInfo,
      newDid,
      newDidParent,
      newDidInnerHash,
      newDidAmount,
      tradePrice,
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
