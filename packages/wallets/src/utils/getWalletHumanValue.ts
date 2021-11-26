import type { Wallet } from '@chia/api';
import { WalletType } from '@chia/api';
import { mojoToCATLocaleString, mojoToChiaLocaleString } from '@chia/core';

export default function getWalletHumanValue(wallet: Wallet, value: number): string {
  return wallet.type === WalletType.CAT
    ? mojoToCATLocaleString(value)
    : mojoToChiaLocaleString(value);
}
