import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import type { RootState } from '../../../modules/rootReducer';
import FarmCard from './FarmCard';

export default function FarmCardPlotCount() {
  const plots = useSelector(
    (state: RootState) => state.farming_state.harvester.plots,
  );

  return (
    <FarmCard
      title={<Trans id="FarmCardPlotCount.title">Plot Count</Trans>}
      value={plots?.length}
      loading={!plots}
    />
  );
}
