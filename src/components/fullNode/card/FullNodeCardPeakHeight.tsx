import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import FarmCard from '../../farm/card/FarmCard';
import { FormatLargeNumber } from '@chia/core';

export default function FullNodeCardPeakHeight() {
  const value = useSelector(
    (state) => state.full_node_state.blockchain_state.peak?.height ?? 0,
  );

  return (
    <FarmCard
      valueColor="textPrimary"
      title={<Trans>Peak Height</Trans>}
      value={<FormatLargeNumber value={value} />}
    />
  );
}
