import React from 'react';
import { Flex, Link } from '@chia/core';
import { Trans } from '@lingui/macro';
import { createTeleporter } from 'react-teleporter';
import { Route, Switch, useRouteMatch } from 'react-router-dom';
import LayoutMain from '../layout/LayoutMain';
import PlotOverview from './overview/PlotOverview';
import PlotAdd from './add/PlotAdd';

const PlotHeaderTeleporter = createTeleporter();

export const PlotHeaderSource = PlotHeaderTeleporter.Source;

export default function Plot() {
  const { path } = useRouteMatch();

  return (
    <LayoutMain
      title={(
        <>
          <Link to="/dashboard/plot" color="textPrimary">
            <Trans id="Plot.title">Plot</Trans>
          </Link>
          <PlotHeaderTeleporter.Target />
        </>
      )}
    >
      <Flex flexDirection="column" gap={3}>
        <Switch>
          <Route path={path} exact>
            <PlotOverview />
          </Route>
          <Route path={`${path}/add`}>
            <PlotAdd />
          </Route>
        </Switch>
      </Flex>
    </LayoutMain>
  );
}
