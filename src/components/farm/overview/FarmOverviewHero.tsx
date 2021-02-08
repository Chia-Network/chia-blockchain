import React from 'react';
import { Trans } from '@lingui/macro';
import { useHistory } from 'react-router-dom';
import { Button, Divider, Grid, Typography } from '@material-ui/core';
import styled from 'styled-components';
import { CardHero, Link } from '@chia/core';
import heroSrc from './images/hero.svg';
import PlotAddDirectoryDialog from '../../plot/PlotAddDirectoryDialog';
import useOpenDialog from '../../../hooks/useOpenDialog';

const StyledImage = styled('img')`
  max-width: 7rem;
`;

export default function FarmOverviewHero() {
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
          <StyledImage src={heroSrc} />
          <Typography variant="body1">
            <Trans>
              Farmers earn block rewards and transaction fees by committing
              spare space to the network to help secure transactions. This
              is where your farm will be once you add a plot.{' '}
              <Link target="_blank" href="https://github.com/Chia-Network/chia-blockchain/wiki/Network-Architecture">Learn more</Link>
            </Trans>
          </Typography>
          <Button
            onClick={handleAddPlot}
            variant="contained"
            color="primary"
          >
            <Trans>Add a Plot</Trans>
          </Button>

          <Divider />

          <Typography variant="body1">
            <Trans>
              {'Do you have existing plots on this machine? '}
              <Link onClick={handleAddPlotDirectory} variant="body1">Add Plot Directory</Link>
            </Trans>
          </Typography>
        </CardHero>
      </Grid>
    </Grid>
  );
}
