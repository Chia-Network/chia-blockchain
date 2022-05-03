import React from 'react';
import { Loading, Flex } from '@chia/core';
import { useGetThrottlePlotQueueQuery, useGetTotalHarvestersSummaryQuery } from '@chia/api-react';
import { Grid } from '@mui/material';
import PlotHero from './PlotOverviewHero';
import PlotOverviewPlots from './PlotOverviewPlots';

export default function PlotOverview() {
  const { isLoading: isLoadingQueue, hasQueue } = useGetThrottlePlotQueueQuery();
  const { isLoading: isLoadingTotalHarvestrSummary, harvesters } = useGetTotalHarvestersSummaryQuery();

  const isLoading = isLoadingQueue || isLoadingTotalHarvestrSummary;
  const hasData = hasQueue || !!harvesters;

  return (
    <Flex flexDirection="column" gap={3}>
      {isLoading ? (
        <Loading center />
      ) : hasData ? (
        <PlotOverviewPlots />
      ) : (
        <Grid container spacing={3}>
          <Grid xs={12} item>
            <PlotHero />
          </Grid>
        </Grid>
      )}
    </Flex>
  );
}
