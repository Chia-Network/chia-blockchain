

import React from 'react';
import { Trans } from '@lingui/macro';
import { FormatLargeNumber, CardSimple } from '@chia/core';
import { useGetTotalHarvestersSummaryQuery } from '@chia/api-react';

export default function PlotCardPlotsFailedToOpen() {
  const { failedToOpenFilenames, initializedHarvesters, isLoading } = useGetTotalHarvestersSummaryQuery();

  return (
    <CardSimple
      title={<Trans>Plots Failed To Open</Trans>}
      value={<FormatLargeNumber value={failedToOpenFilenames} />}
      tooltip={<Trans>These plots are invalid, you might want to delete them.</Trans>}
      loading={isLoading || !initializedHarvesters}
    />
  );
}
