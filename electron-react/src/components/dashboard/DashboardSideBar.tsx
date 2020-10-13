import React from 'react';
import styled from 'styled-components';
import { Trans } from '@lingui/macro';
import { useDispatch } from 'react-redux';
import { List, SvgIcon } from '@material-ui/core';
import { logOut } from '../../modules/message';
import { ReactComponent as WalletsIcon } from './images/wallet.svg';
import { ReactComponent as FarmIcon } from './images/farm.svg';
import { ReactComponent as KeysIcon } from './images/help.svg';
import { ReactComponent as HomeIcon } from './images/home.svg';
import { ReactComponent as PlotIcon } from './images/plot.svg';
import { ReactComponent as TradeIcon } from './images/pool.svg';
import SideBarItem from '../sideBar/SideBarItem';
import Flex from '../flex/Flex';

const StyledHomeIcon = styled(HomeIcon)`
  path {
    stroke: ${({ theme }) =>
      theme.palette.type === 'dark' ? 'white' : '#757575'};;
    stroke-width: 1;
  }
`;

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
          icon={(
            <SvgIcon fontSize="large" component={StyledHomeIcon} viewBox="0 0 32 31" />
          )}
          title={<Trans id="DashboardSideBar.home">Full Node</Trans>}
          exact
        />
        <SideBarItem
          to="/dashboard/wallets"
          icon={(
            <SvgIcon fontSize="large" component={WalletsIcon} viewBox="0 0 32 39" />
          )}
          title={<Trans id="DashboardSideBar.wallets">Wallets</Trans>}
        />
        <SideBarItem
          to="/dashboard/plot"
          icon={(
            <SvgIcon fontSize="large" component={PlotIcon} viewBox="0 0 40 32" />
          )}
          title={<Trans id="DashboardSideBar.plot">Plot</Trans>}
        />
        <SideBarItem
          to="/dashboard/farm"
          icon={(
            <SvgIcon fontSize="large" component={FarmIcon} viewBox="0 0 32 37" />
          )}
          title={<Trans id="DashboardSideBar.farm">Farm</Trans>}
        />
        <SideBarItem
          to="/dashboard/trade"
          icon={(
            <SvgIcon fontSize="large" component={TradeIcon} viewBox="0 0 34 34" />
          )}
          title={<Trans id="DashboardSideBar.trade">Trade</Trans>}
        />
        <SideBarItem
          to="/"
          icon={(
            <SvgIcon fontSize="large" component={KeysIcon} viewBox="0 0 32 33" />
          )}
          onSelect={handleLogOut}
          title={<Trans id="DashboardSideBar.keys">Keys</Trans>}
          exact
        />
      </StyledList>
    </StyledRoot>
  );
}
