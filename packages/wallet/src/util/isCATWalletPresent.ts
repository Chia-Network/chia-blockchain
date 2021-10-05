import type Wallet from '../types/Wallet';
import type CATToken from '../types/CATToken';
import WalletType from '../constants/WalletType';

export default function isCATWalletPresent(wallets: Wallet[], token: CATToken): boolean {
  return !!wallets.find(wallet => wallet.type === WalletType.CAT && wallet.colour === token.tail);
}
