import React from 'react';
import { Trans } from '@lingui/macro';
import { useDispatch } from 'react-redux';
import { useHistory } from 'react-router-dom';
import { Button, Grid, Typography, Divider } from '@material-ui/core';
import { CardHero, Flex, Link } from '@hddcoin/core';
import { PlotHero as PlotHeroIcon } from '@hddcoin/icons';
import PlotAddDirectoryDialog from '../PlotAddDirectoryDialog';
import { refreshPlots } from '../../../modules/harvesterMessages';
import useOpenDialog from '../../../hooks/useOpenDialog';

export default function PlotOverviewHero() {
  const history = useHistory();
  const dispatch = useDispatch();
  const openDialog = useOpenDialog();

  function handleAddPlot() {
    history.push('/dashboard/plot/add');
  }

  function handleAddPlotDirectory() {
    openDialog(<PlotAddDirectoryDialog />);
  }

  function handleRefreshPlots() {
    dispatch(refreshPlots());
  }

  return (
    <Grid container>
      <Grid xs={12} md={6} lg={5} item>
        <CardHero>
          <PlotHeroIcon fontSize="large" />
          <Typography variant="body1">
            <Trans>
              {
                'Plots are allocated space on your hard drive used to farm and earn HDDcoin. '
              }
              <Link
                target="_blank"
                href="https://github.com/HDDcoin-Network/hddcoin-blockchain/wiki/Network-Architecture"
              >
                Learn more
              </Link>
            </Trans>
          </Typography>
          <Flex gap={1}>
            <Button
              onClick={handleAddPlot}
              variant="contained"
              color="primary"
              fullWidth
            >
              <Trans>Add a Plot</Trans>
            </Button>
            <Button
              onClick={handleRefreshPlots}
              variant="outlined"
              color="primary"
              fullWidth
            >
              <Trans>Refresh Plots</Trans>
            </Button>
          </Flex>

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
