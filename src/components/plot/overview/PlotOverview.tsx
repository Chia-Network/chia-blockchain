import React from 'react';
import { Loading, Flex } from '@chia/core';
import { Grid } from '@material-ui/core';
import PlotHero from './PlotOverviewHero';
import PlotOverviewPlots from './PlotOverviewPlots';
import usePlots from '../../../hooks/usePlots';
import PlotsNotFound from '../PlotsNotFound';
import PlotsFailed from '../PlotsFailed';

export default function PlotOverview() {
  const { loading, hasPlots, hasQueue } = usePlots();

  return (
    <Flex flexDirection="column" gap={3}>
      {loading && (
        <Flex alignItems="center" justifyContent="center">
          <Loading />
        </Flex>
      )}

      {!loading && (
        <>
          {(hasPlots || hasQueue) ? (
            <PlotOverviewPlots />
          ) : (
            <Grid container spacing={3}>
              <Grid xs={12} item>
                <PlotHero />
              </Grid>
            </Grid>
          )}

          <PlotsFailed />
          <PlotsNotFound />
        </>
      )}
    </Flex>
  );
}
