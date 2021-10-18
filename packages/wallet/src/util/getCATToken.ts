import Tokens from '../constants/Tokens';
import WalletType from '../constants/WalletType';
import CATToken from '../types/CATToken';
import Wallet from '../types/Wallet';

export default function getCATToken(wallet: Wallet): CATToken | undefined {
  if (wallet.type === WalletType.CAT) {
    return Tokens.find((token) => token.tail === wallet.meta?.tail);
  }
}
