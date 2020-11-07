import React from 'react';
import { Trans } from '@lingui/macro';
import { useHistory } from 'react-router-dom';
import { Button, Grid, Typography, Link } from '@material-ui/core';
import styled from 'styled-components';
import { CardHero } from '@chia/core';
import heroSrc from './images/hero.svg';

const StyledImage = styled('img')`
  max-width: 7rem;
`;

export default function FarmOverviewHero() {
  const history = useHistory();

  function handleAddPlot() {
    history.push('/dashboard/plot/add');
  }

  return (
    <Grid container>
      <Grid xs={12} md={6} lg={4} item>
        <CardHero>
          <StyledImage src={heroSrc} />
          <Typography variant="body1">
            <Trans id="FarmOverviewHero.description">
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
            <Trans id="FarmOverviewHero.addAPlot">Add a Plot</Trans>
          </Button>
        </CardHero>
      </Grid>
    </Grid>
  );
}
