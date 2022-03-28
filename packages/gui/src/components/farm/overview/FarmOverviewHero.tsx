import React from 'react';
import { Trans } from '@lingui/macro';
import { useNavigate, useParams } from 'react-router-dom';
import { Divider, Grid, Typography } from '@mui/material';
import styled from 'styled-components';
import { Button, CardHero, Link, useOpenDialog } from '@chia/core';
import heroSrc from './images/hero.svg';
import PlotAddDirectoryDialog from '../../plot/PlotAddDirectoryDialog';

const StyledImage = styled('img')`
  max-width: 7rem;
`;

export default function FarmOverviewHero() {
  const navigate = useNavigate();
  const openDialog = useOpenDialog();

  function handleAddPlot() {
    navigate('/dashboard/plot/add');
  }

  function handleAddPlotDirectory() {
    openDialog(<PlotAddDirectoryDialog />);
  }

  return (
    <Grid container>
      <Grid xs={12} md={6} lg={5} item>
        <CardHero>
          <StyledImage src={heroSrc} />
          <Typography variant="body1">
            <Trans>
              Farmers earn block rewards and transaction fees by committing
              spare space to the network to help secure transactions. This is
              where your farm will be once you add a plot.{' '}
              <Link
                target="_blank"
                href="https://github.com/Chia-Network/chia-blockchain/wiki/Network-Architecture"
              >
                Learn more
              </Link>
            </Trans>
          </Typography>
          <Button onClick={handleAddPlot} variant="contained" color="primary">
            <Trans>Add a Plot</Trans>
          </Button>

          <Divider />

          <Typography variant="body1">
            <Trans>
              {'Do you have existing plots on this machine? '}
              <Link onClick={handleAddPlotDirectory} variant="body1">
                Add Plot Directory
              </Link>
            </Trans>
          </Typography>
        </CardHero>
      </Grid>
    </Grid>
  );
}
