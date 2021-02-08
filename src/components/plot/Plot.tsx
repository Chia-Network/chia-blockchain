import React from 'react';
import { Flex, Link } from '@chia/core';
import { Trans } from '@lingui/macro';
import { Route, Switch, useRouteMatch } from 'react-router-dom';
import LayoutMain from '../layout/LayoutMain';
import PlotOverview from './overview/PlotOverview';
import PlotAdd from './add/PlotAdd';
import { PlotHeaderTarget }  from './PlotHeader';

export default function Plot() {
  const { path } = useRouteMatch();

  return (
    <LayoutMain
      title={(
        <>
          <Link to="/dashboard/plot" color="textPrimary">
            <Trans>Plot</Trans>
          </Link>
          <PlotHeaderTarget />
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
