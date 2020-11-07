import React from 'react';
import { Loading, Flex } from '@chia/core';
import { Grid } from '@material-ui/core';
import PlotHero from './PlotOverviewHero';
import PlotOverviewPlots from './PlotOverviewPlots';
import usePlots from '../../../hooks/usePlots';

export default function PlotOverview() {
  const { loading, hasPlots } = usePlots();

  return (
    <Flex flexDirection="column" gap={2}>
      {loading ? (
        <Loading />
      ) : hasPlots ? (
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
