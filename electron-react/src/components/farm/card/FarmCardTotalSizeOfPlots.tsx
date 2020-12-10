import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import { FormatBytes } from '@chia/core';
import type { RootState } from '../../../modules/rootReducer';
import FarmCard from './FarmCard';
import type Plot from '../../../types/Plot';

export default function FarmCardTotalSizeOfPlots() {
  const plots = useSelector(
    (state: RootState) => state.farming_state.harvester.plots,
  );

  const farmerSpace = useMemo(() => {
    if (!plots) {
      return 0;
    }

    return plots.map((p: Plot) => p.file_size).reduce((a, b) => a + b, 0);
  }, [plots]);

  return (
    <FarmCard
      title={
        <Trans id="FarmCardTotalSizeOfPlots.title">Total Size of Plots</Trans>
      }
      value={<FormatBytes value={farmerSpace} precision={3} />}
    />
  );
}
