import { useMemo } from 'react';
import { useSelector } from 'react-redux';
import { orderBy } from 'lodash';
import Wallet from '../types/Wallet';
import Transaction from '../types/Transaction';
import type { RootState } from '../modules/rootReducer';
import WalletType from '../constants/WalletType';
import useCurrencyCode from './useCurrencyCode';
import getCATToken from '../util/getCATToken';

export default function useWallet(walletId: number): {
  loading: boolean;
  wallet?: Wallet;
  transactions?: Transaction[];
  unit?: string;
} {
  const currencyCode = useCurrencyCode();
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);

  const wallet = useMemo(() => {
    return wallets?.find((item) => item.id === walletId);
  }, [wallets, walletId]);

  const isLoading = !wallets;

  const transactions = useMemo(() => {
    const transactions = wallet?.transactions;
    if (transactions) {
      return orderBy(
        transactions,
        ['confirmed', 'confirmed_at_height', 'created_at_time'],
        ['asc', 'desc', 'desc'],
      );
    }

    return transactions;
  }, [wallet]);

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

  return { 
    wallet, 
    transactions, 
    loading: isLoading,
    unit,
  };
}
