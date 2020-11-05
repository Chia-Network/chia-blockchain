import React from 'react';
import { Trans } from '@lingui/macro';
import { Loading, Flex } from '@chia/core';
import { Route, Switch } from 'react-router-dom';
import { Button, Breadcrumbs, Divider, Grid, Typography } from '@material-ui/core';
import PlotHero from './PlotOverviewHero';
import usePlots from '../../../hooks/usePlots';

export default function PlotOverview() {
  const { loading, hasPlots } = usePlots();

  return (
    <Flex flexDirection="column" gap={2}>
      {loading ? (
        <Loading />
      ) : !hasPlots ? (
        <PlotOverview />
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
