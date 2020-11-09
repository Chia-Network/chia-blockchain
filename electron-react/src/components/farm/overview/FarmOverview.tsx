import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import { CircularProgress, Typography } from '@material-ui/core';
import type { RootState } from '../../../modules/rootReducer';
import FarmOverviewHero from './FarmOverviewHero';
import FarmOverviewCards from './FarmOverviewCards';

export default function FarmOverview() {
  const plots = useSelector(
    (state: RootState) => state.farming_state.harvester.plots,
  );
  const loading = !plots;
  const hasPlots = !!plots && plots.length > 0;

  return (
    <>
      <Typography variant="h5" gutterBottom>
        <Trans id="Farm.title">Your Farm Overview</Trans>
      </Typography>

      {loading ? (
        <CircularProgress />
      ) : (hasPlots ? (
        <FarmOverviewCards />
      ) : (
        <FarmOverviewHero />
      ))}
    </>
  );
}
