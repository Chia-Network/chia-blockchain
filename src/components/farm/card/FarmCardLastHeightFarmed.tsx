import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import type { RootState } from '../../../modules/rootReducer';
import FarmCard from './FarmCard';

export default function FarmCardLastHeightFarmed() {
  const loading = useSelector(
    (state: RootState) => !state.wallet_state.farmed_amount,
  );

  const lastHeightFarmed = useSelector(
    (state: RootState) => state.wallet_state.farmed_amount?.last_height_farmed,
  );

  return (
    <FarmCard
      title={
        <Trans>Last Height Farmed</Trans>
      }
      value={lastHeightFarmed}
      description={
        !lastHeightFarmed && (
          <Trans>
            No blocks farmed yet
          </Trans>
        )
      }
      loading={loading}
    />
  );
}
