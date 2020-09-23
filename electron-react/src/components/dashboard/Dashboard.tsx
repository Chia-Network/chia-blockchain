import React from "react";
import styled from 'styled-components';
import { Route, Switch, useRouteMatch } from 'react-router';
import { AppBar, Toolbar, Drawer, Typography, Divider, Container } from "@material-ui/core";
import Wallets from "../wallet/Wallets";
import Brand from '../brand/Brand';
import Flex from '../flex/Flex';
import DashboardSideBar from './DashboardSideBar';
import { DashboardTitleTarget } from './DashboardTitle';
import ToolbarSpacing from '../toolbar/ToolbarSpacing';
/*
import Plotter from "./Plotter";
import FullNode from "./FullNode";
import Farmer from "./Farmer";
import { TradeManger } from "./trading/TradeManager";
*/
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

/*
const useStyles = makeStyles(theme => ({
  toolbar: {
    paddingRight: 24 // keep right padding when drawer closed
  },
  appBar: {
    zIndex: theme.zIndex.drawer + 1,
    transition: theme.transitions.create(["width", "margin"], {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.leavingScreen
    })
  },
  menuButton: {
    marginRight: 36
  },
  menuButtonHidden: {
    display: "none"
  },
  title: {
    flexGrow: 1
  },
  appBarSpacer: theme.mixins.toolbar,
  content: {
    flexGrow: 1,
    height: "100vh",
    overflowX: "hidden",
    overflowY: "scroll"
  },
  container: {
    padding: "0px",
    marginLeft: "0px"
  },
  paper: {
    padding: theme.spacing(2),
    display: "flex",
    overflow: "auto",
    flexDirection: "column"
  },
  fixedHeight: {
    height: 240
  },
  drawerWallet: {
    position: "relative",
    whiteSpace: "nowrap",

    height: "100%",
    transition: theme.transitions.create("width", {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.enteringScreen
    })
  },
  logo: {
    marginTop: theme.spacing(2),
    marginBottom: theme.spacing(2),
    marginLeft: theme.spacing(2),
    marginRight: theme.spacing(2),
    width: "62px"
  }
}));

/*
const ComopnentSwitch = () => {
  const toPresent = useSelector(state => state.main_menu.view);

  if (toPresent === presentWallet) {
    return <Wallets></Wallets>;
  } else if (toPresent === presentNode) {
    return <FullNode></FullNode>;
  } else if (toPresent === presentFarmer) {
    return <Farmer></Farmer>;
  } else if (toPresent === presentPlotter) {
    return <Plotter></Plotter>;
  } else if (toPresent === presentTrading) {
    return <TradeManger></TradeManger>;
  }
  return <div></div>;
};
*/

export default function Dashboard() {
  let { path, url } = useRouteMatch();


  /*
  if (toPresent === presentWallet) {
    title = "Wallets";
  } else if (toPresent === presentNode) {
    title = "Full Node";
  } else if (toPresent === presentFarmer) {
    title = "Farming";
  } else if (toPresent === presentPlotter) {
    title = "Plotting";
  } else if (toPresent === presentTrading) {
    title = "Trading";
  }
  */

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
          <StyledBody flexGrow={1} flexDirection="column">
            <ToolbarSpacing />
            <Container maxWidth="md">
              <Switch>
                <Route path={path} exact>
                  <Wallets />
                </Route>
              </Switch>
            </Container>
          </StyledBody>
        {/*
        <CreateBackup />
        */}
      </Flex>
    </StyledRoot>
  );
}
