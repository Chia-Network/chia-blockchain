import React from 'react';
import styled from 'styled-components';
import { Trans } from '@lingui/macro';
import { useDispatch } from 'react-redux';
import { List } from '@material-ui/core';
import {
  Wallet as WalletIcon,
  Farm as FarmIcon,
  Keys as KeysIcon,
  Home as HomeIcon,
  Plot as PlotIcon,
  Trade as TradeIcon,
} from '@chia/icons';
import { Flex, SideBarItem } from '@chia/core';
import { logOut } from '../../modules/message';

const StyledRoot = styled(Flex)`
  height: 100%;
  overflow-y: auto;
`;

const StyledList = styled(List)`
  width: 100%;
`;

export default function DashboardSideBar() {
  const dispatch = useDispatch();

  function handleLogOut() {
    dispatch(logOut('log_out', {}));
  }

  return (
    <StyledRoot>
      <StyledList disablePadding>
        <SideBarItem
          to="/dashboard"
          icon={<HomeIcon fontSize="large" />}
          title={<Trans id="DashboardSideBar.home">Full Node</Trans>}
          exact
        />
        <SideBarItem
          to="/dashboard/wallets"
          icon={<WalletIcon fontSize="large" />}
          title={<Trans id="DashboardSideBar.wallets">Wallets</Trans>}
        />
        <SideBarItem
          to="/dashboard/plot"
          icon={<PlotIcon fontSize="large" />}
          title={<Trans id="DashboardSideBar.plots">Plots</Trans>}
        />
        <SideBarItem
          to="/dashboard/farm"
          icon={<FarmIcon fontSize="large" />}
          title={<Trans id="DashboardSideBar.farm">Farm</Trans>}
        />
        <SideBarItem
          to="/dashboard/trade"
          icon={<TradeIcon fontSize="large" />}
          title={<Trans id="DashboardSideBar.trade">Trade</Trans>}
        />
        <SideBarItem
          to="/"
          icon={<KeysIcon fontSize="large" />}
          onSelect={handleLogOut}
          title={<Trans id="DashboardSideBar.keys">Keys</Trans>}
          exact
        />
      </StyledList>
    </StyledRoot>
  );
}
