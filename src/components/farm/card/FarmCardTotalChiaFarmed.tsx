import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import type { RootState } from '../../../modules/rootReducer';
import FarmCard from './FarmCard';
import { mojo_to_chia } from '../../../util/chia';

export default function FarmCardTotalChiaFarmed() {
  const farmed_amount = useSelector(
    (state: RootState) => state.wallet_state.farmed_amount,
  );

  const totalChiaFarmed = useMemo(() => {
    const val = BigInt(farmed_amount.toString());
    return mojo_to_chia(val);
  }, [farmed_amount]);

  return (
    <FarmCard
      title={<Trans>Total Chia Farmed</Trans>}
      value={totalChiaFarmed}
      loading={false}
    />
  );
}
