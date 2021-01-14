import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import type { RootState } from '../../../modules/rootReducer';
import FarmCard from './FarmCard';
import computeStatistics from '../../../util/computeStatistics';
import { mojo_to_chia } from '../../../util/chia';

export default function FarmCardCoinbaseRewards() {
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);
  const value = computeStatistics(wallets);
  const loading = !wallets;

  const coinbaseRewards = useMemo((): number => mojo_to_chia(value?.coinbaseRewards), [value?.coinbaseRewards]);

  return (
    <FarmCard
      title={
        <Trans id="FarmCardCoinbaseRewards.title">TXCH Farming Rewards</Trans>
      }
      value={coinbaseRewards}
      loading={loading}
    />
  );
}
