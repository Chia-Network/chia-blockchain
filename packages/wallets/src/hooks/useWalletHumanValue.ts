import { useMemo } from 'react';
import type { Wallet } from '@chia/api';
import { WalletType } from '@chia/api';
import BigNumber from 'bignumber.js';
import { mojoToCATLocaleString, mojoToChiaLocaleString, useLocale } from '@chia/core';

export default function useWalletHumanValue(wallet: Wallet, value?: string | number | BigNumber, unit?: string): string {
  const [locale] = useLocale();
  
  return useMemo(() => {
    if (wallet && value !== undefined) {
      const localisedValue = wallet.type === WalletType.CAT
        ? mojoToCATLocaleString(value, locale)
        : mojoToChiaLocaleString(value, locale);

      return `${localisedValue} ${unit}`;
    }

    return '';
  }, [wallet, value, unit, locale]);
}
