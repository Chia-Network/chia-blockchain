import React from "react";
import styled from 'styled-components';
import { Route, Switch, useRouteMatch } from 'react-router';
import { AppBar, Toolbar, Drawer, Divider } from "@material-ui/core";
import Wallets from "../wallet/Wallets";
import FullNode from '../fullNode/FullNode';
import Plotter from '../plotter/Plotter';
import Farmer from '../farmer/Farmer';
import Brand from '../brand/Brand';
import Flex from '../flex/Flex';
import DashboardSideBar from './DashboardSideBar';
import { DashboardTitleTarget } from './DashboardTitle';
import ToolbarSpacing from '../toolbar/ToolbarSpacing';
import TradeManager from "../trading/TradeManager";

// import { CreateBackup } from "./backup/createBackup";

const StyledRoot = styled(Flex)`
  height: 100%;
  overflow: hidden;
`;

const StyledAppBar = styled(AppBar)`
  background-color: white;
  box-shadow: 0px 0px 8px rgba(0, 0, 0, 0.2);
  width: ${({ theme }) => `calc(100% - ${theme.drawer.width})`};
  margin-left: ${({ theme }) => theme.drawer.width};
`;

const StyledDrawer = styled(Drawer)`
  z-index: ${({ theme }) => theme.drawer.zIndex};
  width: ${({ theme }) => theme.drawer.width};
  flex-shrink: 0;

  > div {
    width: ${({ theme }) => theme.drawer.width};
  }
`;

const StyledBody = styled(Flex)`
  box-shadow: inset 6px 0 8px -8px rgba(0, 0, 0, 0.2);
  // padding-top: ${({ theme }) => `${theme.spacing(2)}px`};
  // padding-bottom: ${({ theme }) => `${theme.spacing(2)}px`};
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
      <StyledAppBar
        position="fixed"
        color="transparent"
        elevation={0}
      >
        <Toolbar>
          <DashboardTitleTarget />
        </Toolbar>
      </StyledAppBar>
      <StyledDrawer variant="permanent">
        <StyledBrandWrapper>
          <Brand width={2/3}/>
        </StyledBrandWrapper>
        <Divider />
        <DashboardSideBar />
      </StyledDrawer>
      <Flex flexGrow={1} flexDirection="column">
        <StyledBody flexGrow={1} flexDirection="column" overflow="auto">
          <ToolbarSpacing />
          <Flex overflow="hidden">
            <Switch>
              <Route path={`${path}`} exact>
                <FullNode />
              </Route>
              <Route path={`${path}/wallets`}>
                <Wallets />
              </Route>
              <Route path={`${path}/plot`}>
                <Plotter />
              </Route>
              <Route path={`${path}/farm`}>
                <Farmer />
              </Route>
              <Route path={`${path}/trade`}>
                <TradeManager />
              </Route>
            </Switch>
          </Flex>
        </StyledBody>
        {/*
        <CreateBackup />
        */}
      </Flex>
    </StyledRoot>
  );
}
