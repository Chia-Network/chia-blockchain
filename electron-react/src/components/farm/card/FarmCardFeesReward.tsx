import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import type { RootState } from '../../../modules/rootReducer';
import FarmCard from './FarmCard';
import computeStatistics from '../../../util/computeStatistics';
import { mojo_to_chia } from '../../../util/chia';

export default function FarmCardFeesReward() {
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);
  const value = computeStatistics(wallets);
  const loading = !wallets;

  const feesReward = useMemo((): number => mojo_to_chia(value?.feesReward), [value?.feesReward]);


  return (
    <FarmCard
      title={<Trans id="FarmCardFeesReward.title">TXCH Fees Collected</Trans>}
      value={feesReward}
      loading={loading}
    />
  );
}
