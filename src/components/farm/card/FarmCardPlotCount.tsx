import React from 'react';
import { Trans } from '@lingui/macro';
import FarmCard from './FarmCard';
import usePlots from '../../../hooks/usePlots';

export default function FarmCardPlotCount() {
  const { uniquePlots } = usePlots();

  return (
    <FarmCard
      title={<Trans>Plot Count</Trans>}
      value={uniquePlots?.length}
      loading={!uniquePlots}
    />
  );
}
