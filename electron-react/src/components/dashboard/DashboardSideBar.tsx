import React from "react";
import styled from 'styled-components';
import { Trans } from '@lingui/macro';
import { useDispatch } from "react-redux";
import { List } from "@material-ui/core";
import { logOut } from "../../modules/message";
import { ReactComponent as WalletsIcon} from "../../assets/img/wallet_sidebar.svg";
import { ReactComponent as FarmIcon } from "../../assets/img/farm_sidebar.svg";
import { ReactComponent as KeysIcon } from "../../assets/img/help_sidebar.svg";
import { ReactComponent as HomeIcon } from "../../assets/img/home_sidebar.svg";
import { ReactComponent as PlotIcon } from "../../assets/img/plot_sidebar.svg";
import { ReactComponent as TradeIcon } from "../../assets/img/pool_sidebar.svg";
import SideBarItem from '../sideBar/SideBarItem';
import Flex from '../flex/Flex';

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
    dispatch(logOut("log_out", {}));
  }

  return (
    <StyledRoot>
      <StyledList disablePadding>
        <SideBarItem
          to="/dashboard"
          icon={<HomeIcon />}
          title={(
            <Trans id="DashboardSideBar.home">
              Full Node
            </Trans>
          )}
          exact
        />
        <SideBarItem
          to="/dashboard/wallets"
          icon={<WalletsIcon />}
          title={(
            <Trans id="DashboardSideBar.wallets">
              Wallets
            </Trans>
          )}
        />
        <SideBarItem
          to="/dashboard/plot"
          icon={<PlotIcon />}
          title={(
            <Trans id="DashboardSideBar.plot">
              Plot
            </Trans>
          )}
        />
        <SideBarItem
          to="/dashboard/farm"
          icon={<FarmIcon />}
          title={(
            <Trans id="DashboardSideBar.farm">
              Farm
            </Trans>
          )}
        />
        <SideBarItem
          to="/dashboard/trade"
          icon={<TradeIcon />}
          title={(
            <Trans id="DashboardSideBar.trade">
              Trade
            </Trans>
          )}
        />
        <SideBarItem
          to="/"
          icon={<KeysIcon />}
          onSelect={handleLogOut}
          title={(
            <Trans id="DashboardSideBar.keys">
              Keys
            </Trans>
          )}
          exact
        />
      </StyledList>
    </StyledRoot>
  );
}
