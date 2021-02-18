import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import type { RootState } from '../../../modules/rootReducer';
import FarmCard from './FarmCard';
import computeStatistics from '../../../util/computeStatistics';
import { mojo_to_chia } from '../../../util/chia';

export default function FarmCardUserFees() {
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);
  const value = computeStatistics(wallets);
  const loading = !wallets;

  const userTransactionFees = useMemo((): number => mojo_to_chia(value?.userTransactionFees), [value?.userTransactionFees]);

  return (
    <FarmCard
      title={<Trans>TXCH User Fees</Trans>}
      value={userTransactionFees}
      loading={loading}
    />
  );
}
