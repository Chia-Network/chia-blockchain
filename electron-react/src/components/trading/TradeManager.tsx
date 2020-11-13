import React from 'react';
import { Trans } from '@lingui/macro';
import { Route, Switch, useRouteMatch, useHistory } from 'react-router';
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

  return (
    <LayoutSidebar
      title={<Trans id="TradeManager.title">Trading</Trans>}
      sidebar={(
        <List disablePadding>
          <Divider />
          <span key="trade_overview">
            <ListItem button onClick={() => history.push(url)}>
              <ListItemText
                primary={
                  <Trans id="TradeManager.tradeOverview">Trade Overview</Trans>
                }
                secondary=""
              />
            </ListItem>
          </span>
          <Divider />
          <ListItem button onClick={() => history.push(`${url}/create`)}>
            <ListItemText
              primary={
                <Trans id="TradeManager.createTrade">Create Trade</Trans>
              }
              secondary=""
            />
          </ListItem>
          <Divider />

          <ListItem button onClick={() => history.push(`${url}/offer`)}>
            <ListItemText
              primary={<Trans id="TradeManager.viewTrade">View Trade</Trans>}
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
