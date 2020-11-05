import React from 'react';
import { Trans } from '@lingui/macro';
import { useHistory } from 'react-router-dom';
import { Button, Grid, Typography, Link } from '@material-ui/core';
import { CardHero } from '@chia/core';
import { PlotHero as PlotHeroIcon } from '@chia/icons';

export default function PlotOverviewHero() {
  const history = useHistory();

  function handleAddPlot() {
    history.push('/dashboard/plot/add');
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
        </CardHero>
      </Grid>
    </Grid>
  );
}
