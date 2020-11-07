import React, { useMemo } from 'react';
import { useAsync } from 'react-use';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import type { RootState } from '../../../modules/rootReducer';
import FarmCard from './FarmCard';
import computeStatistics from '../../../util/computeStatistics';
import { mojo_to_chia } from '../../../util/chia';

export default function FarmCardFeesCollected() {
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);
  const { loading, value } = useAsync(() => computeStatistics(wallets), [
    wallets,
  ]);

  const feesCollected = useMemo((): number => mojo_to_chia(value?.feesCollected), [value?.feesCollected]);


  return (
    <FarmCard
      title={<Trans id="FarmCardFeesCollected.title">XCH Fees Collected</Trans>}
      value={feesCollected}
      loading={loading}
    />
  );
}
