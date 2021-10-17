import { useMemo } from 'react';
import { orderBy } from 'lodash';
import { useGetTransactionsQuery } from '@chia/api-react';
import Transaction from '../types/Transaction';

export default function useWalletTransactions(walletId: number): {
  isLoading: boolean;
  transactions?: Transaction[];
} {
  const { data: transactions, isLoading } = useGetTransactionsQuery({
    walletId,
  });

  const transactionsOrdered = useMemo(() => {
    if (transactions) {
      return orderBy(
        transactions,
        ['confirmed', 'confirmedAtHeight', 'createdAtTime'],
        ['asc', 'desc', 'desc'],
      );
    }
  }, [transactions]);

  return { 
    transactions: transactionsOrdered, 
    isLoading,
  };
}
