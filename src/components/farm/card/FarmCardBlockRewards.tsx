import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import type { RootState } from '../../../modules/rootReducer';
import FarmCard from './FarmCard';
import computeStatistics from '../../../util/computeStatistics';
import { mojo_to_chia } from '../../../util/chia';

export default function FarmCardBlockRewards() {
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);
  const value = computeStatistics(wallets);
  const loading = !wallets;

  const blockRewards = useMemo(() => {
    const val = BigInt(value.blockRewards.round().toString());
    return mojo_to_chia(val);
  }, [value.blockRewards]);

  return (
    <FarmCard
      title={<Trans>TXCH Block Rewards</Trans>}
      description={<Trans>Without fees</Trans>}
      value={blockRewards}
      loading={loading}
    />
  );
}
