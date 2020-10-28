import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import type { RootState } from '../../../modules/rootReducer';
import FarmCard from './FarmCard';
import FormatBytes from '../../format/FormatBytes';

export default function FarmCardTotalNetworkSpace() {
  const totalNetworkSpace = useSelector(
    (state: RootState) => state.full_node_state.blockchain_state.space,
  );

  return (
    <FarmCard
      title={
        <Trans id="FarmCardTotalNetworkSpace.title">Total Network Space</Trans>
      }
      value={<FormatBytes value={totalNetworkSpace} />}
      description={
        <Trans id="FarmCardTotalNetworkSpace.tooltip">
          Best estimate over last 1 hour
        </Trans>
      }
    />
  );
}
