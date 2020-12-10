import React from 'react';
import { Trans } from '@lingui/macro';
import { useHistory } from 'react-router-dom';
import { Button, Grid, Typography, Link, Divider } from '@material-ui/core';
import { CardHero } from '@chia/core';
import { PlotHero as PlotHeroIcon } from '@chia/icons';
import PlotAddDirectoryDialog from '../PlotAddDirectoryDialog';
import useOpenDialog from '../../../hooks/useOpenDialog';

export default function PlotOverviewHero() {
  const history = useHistory();
  const openDialog = useOpenDialog();

  function handleAddPlot() {
    history.push('/dashboard/plot/add');
  }

  function handleAddPlotDirectory() {
    openDialog((
      <PlotAddDirectoryDialog />
    ));
  }

  return (
    <Grid container>
      <Grid xs={12} md={6} lg={4} item>
        <CardHero>
          <PlotHeroIcon fontSize="large" />
          <Typography variant="body1">
            <Trans id="PlotHero.description">
              {'Plots are allocated space on your hard drive used to farm and earn Chia. '}
              <Link target="_blank" href="https://github.com/Chia-Network/chia-blockchain/wiki/Network-Architecture">Learn more</Link>
            </Trans>
          </Typography>
          <Button
            onClick={handleAddPlot}
            variant="contained"
            color="primary"
          >
            <Trans id="PlotHero.addAPlot">Add a Plot</Trans>
          </Button>

          <Divider />

          <Typography variant="body1">
            <Trans id="PlotHero.doYouHavePlot">
              {'Do you have existing plots on this machine? '}
              <Link onClick={handleAddPlotDirectory} variant="body1" component="button">Add Plot Directory</Link>
            </Trans>
          </Typography>
        </CardHero>
      </Grid>
    </Grid>
  );
}
