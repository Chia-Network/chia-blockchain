import type Wallet from '../types/Wallet';
import type CATToken from '../types/CATToken';
import WalletType from '../constants/WalletType';

export default function isCATWalletPresent(wallets: Wallet[], token: CATToken): boolean {
  return !!wallets?.find((wallet) => {
    if (wallet.type === WalletType.CAT && wallet.meta?.tail === token.assetId) {
      return true;
    }

    return false;
  });
}
