import { WalletType } from '@chia/api';
import type { Wallet } from '@chia/api';

export default function getWalletPrimaryTitle(wallet: Wallet): string {
  switch (wallet.type) {
    case WalletType.STANDARD_WALLET:
      return 'Chia';
    default:
      return wallet.meta?.name ?? wallet.name;
  }
}
