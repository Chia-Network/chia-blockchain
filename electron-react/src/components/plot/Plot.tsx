import React from 'react';
import { Flex } from '@chia/core';
import { Trans } from '@lingui/macro';
import { Route, Switch, useRouteMatch } from 'react-router-dom';
import LayoutMain from '../layout/LayoutMain';
import PlotOverview from './overview/PlotOverview';
import PlotHeader from './PlotHeader';
import PlotAdd from './add/PlotAdd';

export default function Plot() {
  const { path } = useRouteMatch();

  return (
    <LayoutMain title={<Trans id="Plot.title">Plot</Trans>}>
      <Flex flexDirection="column" gap={2}>
        <PlotHeader />
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
