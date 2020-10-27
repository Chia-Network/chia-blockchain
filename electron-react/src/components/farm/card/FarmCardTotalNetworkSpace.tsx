import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
// @ts-ignore
import byteSize from 'byte-size';
import type { RootState } from '../../../modules/rootReducer';
import FarmCard from './FarmCard';

export default function FarmCardTotalNetworkSpace() {
  const totalNetworkSpace = useSelector(
    (state: RootState) => state.full_node_state.blockchain_state.space,
  );

  const { value, unit } = byteSize(totalNetworkSpace, { units: 'iec' });

  return (
    <FarmCard
      title={<Trans id="FarmCardTotalNetworkSpace.title">Total Network Space</Trans>}
      value={`${value} ${unit}`}
      description={(
        <Trans id="FarmCardTotalNetworkSpace.tooltip">
          Best estimate over last 1 hour
        </Trans>
      )}
    />
  );
}
