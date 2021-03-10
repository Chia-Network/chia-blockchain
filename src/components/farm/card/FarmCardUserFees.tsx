import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import type { RootState } from '../../../modules/rootReducer';
import FarmCard from './FarmCard';
import computeStatistics from '../../../util/computeStatistics';
import { mojo_to_chia } from '../../../util/chia';
import useCurrencyCode from '../../../hooks/useCurrencyCode';

export default function FarmCardUserFees() {
  const currencyCode = useCurrencyCode();
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);
  const value = computeStatistics(wallets);
  const loading = !wallets;

  const userTransactionFees = useMemo(() => {
    const val = BigInt(value.userTransactionFees.round().toString());
    return mojo_to_chia(val);
  }, [value.userTransactionFees]);

  return (
    <FarmCard
      title={<Trans>{currencyCode} User Transaction Fees</Trans>}
      value={userTransactionFees}
      loading={loading}
    />
  );
}
