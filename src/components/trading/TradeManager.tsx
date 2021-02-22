import React from 'react';
import { Trans } from '@lingui/macro';
import { Route, Switch, useLocation, useHistory, useRouteMatch } from 'react-router';
import {
  Grid,
  List,
  Divider,
  ListItem,
  ListItemText,
} from '@material-ui/core';
import { OfferSwitch } from './ViewOffer';
import { TradingOverview } from './TradingOverview';
import CreateOffer from './CreateOffer';
import LayoutSidebar from '../layout/LayoutSidebar';

export default function TradeManager() {
  const { path, url } = useRouteMatch();
  const history = useHistory();
  const { pathname } = useLocation();

  return (
    <LayoutSidebar
      title={<Trans>Trading</Trans>}
      sidebar={(
        <List disablePadding>
          <Divider />
          <span key="trade_overview">
            <ListItem
              onClick={() => history.push(url)}
              selected={pathname === '/dashboard/trade'}
              button
            >
              <ListItemText
                primary={
                  <Trans>Trade Overview</Trans>
                }
                secondary=""
              />
            </ListItem>
          </span>
          <Divider />
          <ListItem
            selected={pathname === '/dashboard/trade/create'}
            onClick={() => history.push(`${url}/create`)}
            button
          >
            <ListItemText
              primary={
                <Trans>Create Offer</Trans>
              }
              secondary=""
            />
          </ListItem>
          <Divider />

          <ListItem
            onClick={() => history.push(`${url}/offer`)}
            selected={pathname === '/dashboard/trade/offer'}
            button
          >
            <ListItemText
              primary={<Trans>View Offer</Trans>}
              secondary=""
            />
          </ListItem>
          <Divider />
        </List>
      )}
    >
      <Grid container spacing={3}>
        {/* Chart */}
        <Grid item xs={12}>
          <Switch>
            <Route path={path} exact>
              <TradingOverview />
            </Route>
            <Route path={`${path}/create`}>
              <CreateOffer />
            </Route>
            <Route path={`${path}/offer`}>
              <OfferSwitch />
            </Route>
          </Switch>
        </Grid>
        <Grid item xs={12} />
      </Grid>
    </LayoutSidebar>
  );
}
