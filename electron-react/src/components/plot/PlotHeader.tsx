import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex, Link } from '@chia/core';
import { useHistory } from 'react-router-dom';
import { createTeleporter } from 'react-teleporter';
import { Button, Breadcrumbs, Divider, Grid, Typography } from '@material-ui/core';
import { NavigateNext as NavigateNextIcon } from '@material-ui/icons';

const PlotHeaderTeleporter = createTeleporter();

export const PlotHeaderSource = PlotHeaderTeleporter.Source;

export default function PlotHeader() {
  const history = useHistory();

  function handleAddPlot() {
    history.push('/dashboard/plot/add');
  }

  return (
    <div>
      <Flex alignItems="center">
        <Flex flexGrow={1}>
          <Breadcrumbs separator={<NavigateNextIcon fontSize="small" />}>
            <Link to="/dashboard/plot">
              <Typography color="textPrimary">
                <Trans id="PlotHeader.title">Plot</Trans>
              </Typography>
            </Link>
            <PlotHeaderTeleporter.Target />
          </Breadcrumbs>
        </Flex>
        <Button color="primary" onClick={handleAddPlot}>
          <Trans id="PlotHeader.addAPlot">+ Add a Plot</Trans>
        </Button>
      </Flex>
      <Divider />
    </div>
  );
}
