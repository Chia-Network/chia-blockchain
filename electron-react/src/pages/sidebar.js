import React from "react";
import {
  presentWallet,
  presentNode,
  presentFarmer,
  changeMainMenu,
  presentTrading,
  presentPlotter
} from "../modules/mainMenu";
import { useSelector } from "react-redux";
import { logOut } from "../modules/message";
import { useDispatch } from "react-redux";
import List from "@material-ui/core/List";
import Divider from "@material-ui/core/Divider";

import { changeEntranceMenu, presentSelectKeys } from "../modules/entranceMenu";
import walletSidebarLogo from "../assets/img/wallet_sidebar.svg"; // Tell webpack this JS file uses this image
import farmSidebarLogo from "../assets/img/farm_sidebar.svg";
import helpSidebarLogo from "../assets/img/help_sidebar.svg";
import homeSidebarLogo from "../assets/img/home_sidebar.svg";
import plotSidebarLogo from "../assets/img/plot_sidebar.svg";
import poolSidebarLogo from "../assets/img/pool_sidebar.svg";
import { makeStyles } from "@material-ui/core/styles";

const useStyles = makeStyles(theme => ({
  div: {
    textAlign: "center",
    cursor: "pointer"
  },
  label: {
    fontFamily: "Roboto",
    fontWeight: "300",
    fontSize: "16px",
    fontStyle: "normal",
    marginTop: "5px"
  },
  labelChosen: {
    fontFamily: "Roboto",
    fontWeight: "500",
    fontSize: "16px",
    fontStyle: "normal",
    marginTop: "5px"
  }
}));

const menuItems = [
  {
    label: "Full Node",
    present: presentNode,
    icon: <img src={homeSidebarLogo} alt="Logo" />
  },
  {
    label: "Wallet",
    present: presentWallet,
    icon: <img src={walletSidebarLogo} alt="Logo" />
  },
  {
    label: "Plot",
    present: presentPlotter,
    icon: <img src={plotSidebarLogo} alt="Logo" />
  },
  {
    label: "Farm",
    present: presentFarmer,
    icon: <img src={farmSidebarLogo} alt="Logo" />
  },
  {
    label: "Trade",
    present: presentTrading,
    icon: <img src={poolSidebarLogo} alt="Logo" />
  },
  {
    label: "Keys",
    changeKeys: true,
    icon: <img src={helpSidebarLogo} alt="Logo" />
  }
];

const MenuItem = (menuItem, currentView) => {
  const classes = useStyles();
  const dispatch = useDispatch();
  const item = menuItem;

  function presentMe() {
    if (item.changeKeys) {
      dispatch(logOut("log_out", {}));
      dispatch(changeEntranceMenu(presentSelectKeys));
    } else {
      dispatch(changeMainMenu(item.present));
    }
  }
  const labelClass =
    currentView === item.present ? classes.labelChosen : classes.label;

  return (
    <div className={classes.div} onClick={presentMe} key={item.label}>
      {item.icon}
      <p className={labelClass}>{item.label}</p>
    </div>
  );
};

export const SideBar = () => {
  const currentView = useSelector(state => state.main_menu.view);
  return (
    <div>
      <List>{menuItems.map(item => MenuItem(item, currentView))}</List>
      <Divider />
    </div>
  );
};
