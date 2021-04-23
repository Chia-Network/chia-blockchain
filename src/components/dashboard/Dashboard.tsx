import React from 'react';
import styled from 'styled-components';
import { Route, Switch, useRouteMatch } from 'react-router';
import { Box, AppBar, Toolbar, Drawer, Divider } from '@material-ui/core';
import {
  DarkModeToggle,
  LocaleToggle,
  Flex,
  Logo,
  ToolbarSpacing,
} from '@chia/core';
import { defaultLocale, locales } from '../../config/locales';
import Wallets from '../wallet/Wallets';
import FullNode from '../fullNode/FullNode';
import Plot from '../plot/Plot';
import Farm from '../farm/Farm';
import Block from '../block/Block';
import DashboardSideBar from './DashboardSideBar';
import { DashboardTitleTarget } from './DashboardTitle';
import TradeManager from '../trading/TradeManager';
import BackupCreate from '../backup/BackupCreate';

const StyledRoot = styled(Flex)`
  height: 100%;
  // overflow: hidden;
`;

const StyledAppBar = styled(AppBar)`
  background-color: ${({ theme }) =>
    theme.palette.type === 'dark' ? '#424242' : 'white'};
  box-shadow: 0px 0px 8px rgba(0, 0, 0, 0.2);
  width: ${({ theme }) => `calc(100% - ${theme.drawer.width})`};
  margin-left: ${({ theme }) => theme.drawer.width};
  z-index: ${({ theme}) => theme.zIndex.drawer + 1};
`;

const StyledDrawer = styled(Drawer)`
  z-index: ${({ theme}) => theme.zIndex.drawer + 2};
  width: ${({ theme }) => theme.drawer.width};
  flex-shrink: 0;

  > div {
    width: ${({ theme }) => theme.drawer.width};
  }
`;

const StyledBody = styled(Box)`
  min-width: 0;
`;

const StyledBrandWrapper = styled(Flex)`
  height: 64px;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  // border-right: 1px solid rgba(0, 0, 0, 0.12);
`;

export default function Dashboard() {
  const { path } = useRouteMatch();

  return (
    <StyledRoot>
      <BackupCreate />
      <StyledAppBar position="fixed" color="transparent" elevation={0}>
        <Toolbar>
          <DashboardTitleTarget />
          <Flex flexGrow={1} />
          <LocaleToggle locales={locales} defaultLocale={defaultLocale} />
          <DarkModeToggle />
        </Toolbar>
      </StyledAppBar>
      <StyledDrawer variant="permanent">
        <StyledBrandWrapper>
          <Logo width={2 / 3} />
        </StyledBrandWrapper>
        <Divider />
        <DashboardSideBar />
      </StyledDrawer>
      <StyledBody flexGrow={1}>
        <ToolbarSpacing />
        <Switch>
          <Route path={`${path}`} exact>
            <FullNode />
          </Route>
          <Route path={`${path}/block/:headerHash`} exact>
            <Block />
          </Route>
          <Route path={`${path}/wallets`}>
            <Wallets />
          </Route>
          <Route path={`${path}/plot`}>
            <Plot />
          </Route>
          <Route path={`${path}/farm`}>
            <Farm />
          </Route>
          <Route path={`${path}/trade`}>
            <TradeManager />
          </Route>
        </Switch>
      </StyledBody>
    </StyledRoot>
  );
}
