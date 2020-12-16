import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import { FormatBytes } from '@chia/core';
import type { RootState } from '../../../modules/rootReducer';
import FarmCard from './FarmCard';

export default function FarmCardTotalNetworkSpace() {
  const totalNetworkSpace = useSelector(
    (state: RootState) => state.full_node_state.blockchain_state?.space ?? 0,
  );

  return (
    <FarmCard
      title={
        <Trans id="FarmCardTotalNetworkSpace.title">Total Network Space</Trans>
      }
      value={<FormatBytes value={totalNetworkSpace} precision={3} />}
      description={
        <Trans id="FarmCardTotalNetworkSpace.tooltip">
          Best estimate over last 1 hour
        </Trans>
      }
    />
  );
}
