import React from 'react';
import { useAsync } from 'react-use';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import type { RootState } from '../../../modules/rootReducer';
import FarmCard from './FarmCard';
import computeStatistics from '../../../util/computeStatistics';

export default function FarmCardTotalChiaFarmed() {
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);
  const { loading, value } = useAsync(() => computeStatistics(wallets), [
    wallets,
  ]);

  return (
    <FarmCard
      title={
        <Trans id="FarmCardTotalChiaFarmed.title">Total Chia Farmed</Trans>
      }
      value={value?.totalChia.toString()}
      loading={loading}
    />
  );
}
