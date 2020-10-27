import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
// @ts-ignore
import byteSize from 'byte-size';
import type { RootState } from '../../../modules/rootReducer';
import FarmCard from './FarmCard';
import type Plot from '../../../types/Plot';

export default function FarmCardTotalSizeOfPlots() {
  const plots = useSelector((state: RootState) => state.farming_state.harvester.plots);
  const totalNetworkSpace = useSelector(
    (state: RootState) => state.full_node_state.blockchain_state.space,
  );

  const farmerSpace = useMemo(() => {
    if (!plots) {
      return 0;
    }

    return plots
      .map((p: Plot) => p.file_size)
      .reduce((a, b) => a + b, 0);
  }, [plots]);

  const proportion = totalNetworkSpace
    ? farmerSpace / totalNetworkSpace
    : 0;
  const totalHours = proportion
    ? 5 / proportion / 60
    : Number.POSITIVE_INFINITY;

  const { value, unit } = byteSize(farmerSpace, { units: 'iec' });

  return (
    <FarmCard
      title={<Trans id="FarmCardTotalSizeOfPlots.title">Total Size of Plots</Trans>}
      value={`${value} ${unit}`}
      tooltip={(
        <Trans id="FarmCardTotalSizeOfPlots.tooltip">
          You have {(proportion * 100).toFixed(6)}%
          of the space on the network, so farming a block will take
          {totalHours.toFixed(3)} hours in expectation
        </Trans>
      )}
    />
  );
}
