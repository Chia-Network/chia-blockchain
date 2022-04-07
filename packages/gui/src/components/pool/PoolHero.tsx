import React from 'react';
import styled from 'styled-components';
import { Trans } from '@lingui/macro';
import { useNavigate } from 'react-router-dom';
import { Grid, Typography } from '@mui/material';
import { Button, CardHero } from '@chia/core';
import { Pooling } from '@chia/icons';

export default function PoolHero() {
  const navigate = useNavigate();

  function handleJoinPool() {
    navigate('/dashboard/pool/add');
  }

  return (
    <Grid container>
      <Grid xs={12} md={6} lg={5} item>
        <CardHero>
          <Pooling color="primary" fontSize="extraLarge" />
          <Typography variant="body1">
            <Trans>
              Smooth out your XCH farming rewards by joining a pool.
            </Trans>
          </Typography>
          <Button onClick={handleJoinPool} variant="contained" color="primary">
            <Trans>Join a Pool</Trans>
          </Button>
        </CardHero>
      </Grid>
    </Grid>
  );
}
