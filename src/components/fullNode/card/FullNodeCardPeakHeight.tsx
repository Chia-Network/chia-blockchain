import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import FarmCard from '../../farm/card/FarmCard';
import { FormatLargeNumber } from '@chia/core';
import { RootState } from '../../../modules/rootReducer';

export default function FullNodeCardPeakHeight() {
  const state = useSelector(
    (state: RootState) => state.full_node_state.blockchain_state,
  );

  const loading = !state;
  const value = state?.peak?.height ?? 0;

  return (
    <FarmCard
      loading={loading}
      valueColor="textPrimary"
      title={<Trans>Peak Height</Trans>}
      value={<FormatLargeNumber value={value} />}
    />
  );
}
