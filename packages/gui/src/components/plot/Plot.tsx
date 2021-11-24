import React from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Flex, Link } from '@chia/core';
import { Trans } from '@lingui/macro';
import { Route, Switch, useRouteMatch } from 'react-router-dom';
import LayoutMain from '../layout/LayoutMain';
import PlotOverview from './overview/PlotOverview';
import PlotAdd from './add/PlotAdd';
import { PlotHeaderTarget } from './PlotHeader';
import { getPlotters } from '../../modules/plotter_messages';
import { RootState } from '../../modules/rootReducer';

export default function Plot() {
  const { path } = useRouteMatch();
  const dispatch = useDispatch();
  const fetchedPlotters = useSelector((state: RootState) => state.plotter_configuration.fetchedPlotters);

  // Probe for available plotters to be used by the PlotAdd component
  if (fetchedPlotters === false) {
    dispatch(getPlotters());
  }

  return (
    <LayoutMain
      title={
        <>
          <Link to="/dashboard/plot" color="textPrimary">
            <Trans>Plot</Trans>
          </Link>
          <PlotHeaderTarget />
        </>
      }
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
