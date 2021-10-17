import { useMemo } from 'react';
import { useGetWalletsQuery } from '@chia/api-react';
import Wallet from '../types/Wallet';
import WalletType from '../constants/WalletType';
import useCurrencyCode from './useCurrencyCode';
import getCATToken from '../util/getCATToken';

export default function useWallet(walletId: number): {
  loading: boolean;
  wallet?: Wallet;
  unit?: string;
  data?: any;
} {
  const currencyCode = useCurrencyCode();
  const { data: wallets, isLoading } = useGetWalletsQuery();

  const wallet = useMemo(() => {
    return wallets?.find((item) => item.id === walletId);
  }, [wallets, walletId]);

  const unit = useMemo(() => {
    if (wallet) {
      if (wallet.type === WalletType.CAT) {
        const token = getCATToken(wallet);
        if (token) {
          return token.symbol;
        }

        return undefined;
      }
      
      return currencyCode;
    } 
  }, [wallet, currencyCode]);

  const data = useMemo(() => {
    if (wallet?.data) {
      return JSON.parse(wallet.data);
    }

  }, [wallet?.data]);

  return { 
    wallet, 
    loading: isLoading,
    unit,
    data,
  };
}
