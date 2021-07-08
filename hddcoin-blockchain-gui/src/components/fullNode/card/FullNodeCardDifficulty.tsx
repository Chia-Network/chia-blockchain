import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import FarmCard from '../../farm/card/FarmCard';
import { FormatLargeNumber } from '@hddcoin/core';
import type { RootState } from '../../../modules/rootReducer';

export default function FullNodeCardDifficulty() {
  const state = useSelector(
    (state: RootState) => state.full_node_state.blockchain_state,
  );

  const loading = !state;
  const value = state?.difficulty;

  return (
    <FarmCard
      loading={loading}
      valueColor="textPrimary"
      title={<Trans>Difficulty</Trans>}
      value={<FormatLargeNumber value={value} />}
    />
  );
}
