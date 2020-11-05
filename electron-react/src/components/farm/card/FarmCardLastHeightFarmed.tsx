import React from 'react';
import { useAsync } from 'react-use';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import type { RootState } from '../../../modules/rootReducer';
import FarmCard from './FarmCard';
import computeStatistics from '../../../util/computeStatistics';

export default function FarmCardLastHeightFarmed() {
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);
  const { loading, value } = useAsync(() => computeStatistics(wallets), [
    wallets,
  ]);

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
