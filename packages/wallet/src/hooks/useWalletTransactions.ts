import { useMemo, useState } from 'react';
import { orderBy } from 'lodash';
import { useGetTransactionsQuery, useGetTransactionsCountQuery } from '@chia/api-react';
import Transaction from '../types/Transaction';

export default function useWalletTransactions(walletId: number, defaultRowsPerPage: number = 10, defaultPage: number = 0): {
  isLoading: boolean;
  transactions?: Transaction[];
  count?: number;
  error?: Error;
  page: number;
  rowsPerPage: number;
  pageChange: (rowsPerPage: number, page: number) => void;
} {
  const [rowsPerPage, setRowsPerPage] = useState<number>(defaultRowsPerPage);
  const [page, setPage] = useState<number>(defaultPage);

  const { data: count, isLoading: isTransactionsCountLoading, error: transactionsCountError } = useGetTransactionsCountQuery({
    walletId,
  });

  const all = rowsPerPage === -1;

  const start = all 
    ? 0 
    : page * rowsPerPage;

  const end = all 
    ? count ?? 0 
    : start + rowsPerPage;

  const { data: transactions, isLoading: isTransactionsLoading, error: transactionsError } = useGetTransactionsQuery({
    walletId,
    start,
    end,
  }, {
    skipToken: count === undefined,
  });

  const isLoading = isTransactionsLoading || isTransactionsCountLoading;
  const error = transactionsError || transactionsCountError;

  // TODO move sorting to the backend
  const transactionsOrdered = useMemo(() => {
    if (transactions) {
      return orderBy(
        transactions,
        ['confirmed', 'confirmedAtHeight', 'createdAtTime'],
        ['asc', 'desc', 'desc'],
      );
    }
  }, [transactions]);

  function handlePageChange(rowsPerPage: number, page: number) {
    setRowsPerPage(rowsPerPage);
    setPage(page);
  }

  return { 
    transactions: transactionsOrdered, 
    count,
    page, 
    rowsPerPage,
    isLoading,
    error,
    pageChange: handlePageChange,
  };
}
