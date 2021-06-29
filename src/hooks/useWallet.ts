import { useMemo } from 'react';
import { useSelector } from 'react-redux';
import { orderBy } from 'lodash';
import Wallet from '../types/Wallet';
import Transaction from '../types/Transaction';
import type { RootState } from '../modules/rootReducer';

export default function useWallet(walletId: number): {
  loading: boolean;
  wallet?: Wallet;
  transactions?: Transaction[];
} {
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);

  const wallet = useMemo(() => {
    return wallets?.find((item) => item.id === walletId);
  }, [wallets, walletId]);

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

  return { wallet, transactions, loading: !wallets };
}
