import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import type { RootState } from '../../../modules/rootReducer';
import FarmCard from './FarmCard';
import { mojo_to_chia } from '../../../util/chia';

export default function FarmCardTotalChiaFarmed() {
  const loading = useSelector(
    (state: RootState) => !state.wallet_state.farmed_amount,
  );

  const farmedAmount = useSelector(
    (state: RootState) => state.wallet_state.farmed_amount?.farmed_amount,
  );

  const totalChiaFarmed = useMemo(() => {
    if (farmedAmount !== undefined) {
      const val = BigInt(farmedAmount.toString());
      return mojo_to_chia(val);
    }
  }, [farmedAmount]);

  return (
    <FarmCard
      title={<Trans>Total Chia Farmed</Trans>}
      value={totalChiaFarmed}
      loading={loading}
    />
  );
}
