import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import type { RootState } from '../../../modules/rootReducer';
import FarmCard from './FarmCard';
import computeStatistics from '../../../util/computeStatistics';
import { mojo_to_chia } from '../../../util/chia';

export default function FarmCardTotalChiaFarmed() {
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);
  const value = computeStatistics(wallets);
  const loading = !wallets;

  const total = useMemo((): number => mojo_to_chia(value?.totalChia), [value?.totalChia]);

  return (
    <FarmCard
      title={
        <Trans id="FarmCardTotalChiaFarmed.title">Total Chia Farmed</Trans>
      }
      value={total}
      loading={loading}
    />
  );
}
