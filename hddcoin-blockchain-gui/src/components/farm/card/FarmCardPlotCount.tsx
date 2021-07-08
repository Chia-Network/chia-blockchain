import React from 'react';
import { Trans } from '@lingui/macro';
import { FormatLargeNumber } from '@hddcoin/core';
import FarmCard from './FarmCard';
import usePlots from '../../../hooks/usePlots';

export default function FarmCardPlotCount() {
  const { uniquePlots } = usePlots();

  return (
    <FarmCard
      title={<Trans>Plot Count</Trans>}
      value={<FormatLargeNumber value={uniquePlots?.length} />}
      loading={!uniquePlots}
    />
  );
}
