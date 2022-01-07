import { useEffect, useState } from 'react';
import { useDispatch } from 'react-redux';
import { useInterval } from 'react-use';
import { getTransaction } from '../modules/incoming';
import type Transaction from '../types/Transaction';

export default function useTransaction(
  transactionId: string,
  delay = 1000,
): [Transaction | undefined] {
  const dispatch = useDispatch();
  const [transaction, setTransaction] = useState<Transaction | undefined>();
  const isConfirmed = !!transaction?.confirmed;

  async function getTransactionDetails() {
    if (transaction?.confirmed) {
      return;
    }

    const updatedTransaction = await dispatch<Transaction>(
      getTransaction(transactionId),
    );
    setTransaction(updatedTransaction);
  }

  useEffect(() => {
    if (!isConfirmed) {
      getTransactionDetails();
    }
  }, [transactionId]);

  useInterval(
    () => {
      getTransactionDetails();
    },
    isConfirmed ? null : delay,
  );

  return [transaction];
}
