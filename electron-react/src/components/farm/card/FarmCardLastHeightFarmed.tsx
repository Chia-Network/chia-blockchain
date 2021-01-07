import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import type { RootState } from '../../../modules/rootReducer';
import FarmCard from './FarmCard';
import computeStatistics from '../../../util/computeStatistics';

export default function FarmCardLastHeightFarmed() {
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);
  const value = computeStatistics(wallets);
  const loading = !wallets;

  const biggestHeight = value?.biggestHeight;

  return (
    <FarmCard
      title={
        <Trans id="FarmCardLastHeightFarmed.title">Last Height Farmed</Trans>
      }
      value={biggestHeight}
      description={
        !biggestHeight && (
          <Trans id="FarmCardLastHeightFarmed.noBlocksFarmedYet">
            No blocks farmed yet
          </Trans>
        )
      }
      loading={loading}
    />
  );
}
