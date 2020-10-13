import React from 'react';
import { Trans } from '@lingui/macro';
import { makeStyles } from '@material-ui/core/styles';
import { Route, Switch, useRouteMatch, useHistory } from 'react-router';
import clsx from 'clsx';
import {
  Drawer,
  Grid,
  Container,
  List,
  Divider,
  ListItem,
  ListItemText,
} from '@material-ui/core';
import { OfferSwitch } from './ViewOffer';
import { TradingOverview } from './TradingOverview';
import CreateOffer from './CreateOffer';
import DashboardTitle from '../dashboard/DashboardTitle';
import Flex from '../flex/Flex';

const drawerWidth = 180;

const useStyles = makeStyles((theme) => ({
  menuButton: {
    marginRight: 36,
  },
  menuButtonHidden: {
    display: 'none',
  },
  title: {
    flexGrow: 1,
  },
  drawerPaper: {
    position: 'relative',
    whiteSpace: 'nowrap',
    width: drawerWidth,
  },
  drawerWallet: {
    position: 'relative',
    whiteSpace: 'nowrap',
    width: drawerWidth,
    height: '100%',
    transition: theme.transitions.create('width', {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.enteringScreen,
    }),
  },
  balancePaper: {
    height: 200,
    marginTop: theme.spacing(2),
  },
  bottomOptions: {
    position: 'absolute',
    bottom: 0,
    width: '100%',
  },
}));

export default function TradeManager() {
  const classes = useStyles();
  const { path, url } = useRouteMatch();
  const history = useHistory();

  return (
    <>
      <DashboardTitle>
        <Trans id="TradeManager.title">
          Trading
        </Trans>
      </DashboardTitle>
      <Drawer
        variant="permanent"
        classes={{
          paper: clsx(classes.drawerPaper),
        }}
      >
        <List disablePadding>
          <Divider />
          <span key="trade_overview">
            <ListItem button onClick={() => history.push(url)}>
              <ListItemText
                primary={<Trans id="TradeManager.tradeOverview">Trade Overview</Trans>}
                secondary=""
              />
            </ListItem>
          </span>
          <Divider />
          <ListItem button onClick={() => history.push(`${url}/create`)}>
            <ListItemText
              primary={<Trans id="TradeManager.createTrade">Create Trade</Trans>}
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
      </Drawer>
      <Flex flexDirection="column" flexGrow={1} height="100%" overflow="auto">
        <Container maxWidth="lg">
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
        </Container>
      </Flex>
    </>
  );
}
