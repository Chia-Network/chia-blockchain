import React from "react";
import clsx from "clsx";
import { makeStyles } from "@material-ui/core/styles";
import CssBaseline from "@material-ui/core/CssBaseline";
import Drawer from "@material-ui/core/Drawer";
import AppBar from "@material-ui/core/AppBar";
import Toolbar from "@material-ui/core/Toolbar";
import Typography from "@material-ui/core/Typography";
import Divider from "@material-ui/core/Divider";
import Container from "@material-ui/core/Container";
import logo from "../assets/img/chia_logo.svg"; // Tell webpack this JS file uses this image
import Wallets from "./Wallets";
import { SideBar } from "./sidebar";
import { useSelector } from "react-redux";
import Plotter from "./Plotter";
import {
  presentWallet,
  presentNode,
  presentFarmer,
  presentTrading,
  presentPlotter
} from "../modules/mainMenu";
import FullNode from "./FullNode";
import Farmer from "./Farmer";
import { TradeManger } from "./trading/TradeManager";
import { CreateBackup } from "./backup/createBackup";

const drawerWidth = 100;

const useStyles = makeStyles(theme => ({
  root: {
    display: "flex"
  },
  toolbar: {
    paddingRight: 24 // keep right padding when drawer closed
  },
  toolbarIcon: {
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-end",
    padding: "0 8px",
    ...theme.mixins.toolbar
  },
  appBar: {
    zIndex: theme.zIndex.drawer + 1,
    transition: theme.transitions.create(["width", "margin"], {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.leavingScreen
    })
  },
  appBarShift: {
    marginLeft: drawerWidth,
    width: `calc(100% - ${drawerWidth}px)`,
    transition: theme.transitions.create(["width", "margin"], {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.enteringScreen
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
  drawerPaper: {
    position: "relative",
    whiteSpace: "nowrap",
    width: drawerWidth,
    transition: theme.transitions.create("width", {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.enteringScreen
    })
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
    width: drawerWidth,
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

export default function Dashboard() {
  const classes = useStyles();
  const [open] = React.useState(true);
  const toPresent = useSelector(state => state.main_menu.view);
  let title;
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

  return (
    <div className={classes.root}>
      <CssBaseline />
      <AppBar
        position="absolute"
        className={clsx(classes.appBar, open && classes.appBarShift)}
      >
        <Toolbar className={classes.toolbar}>
          <Typography
            component="h1"
            variant="h6"
            color="inherit"
            noWrap
            className={classes.title}
          >
            {title}
          </Typography>
        </Toolbar>
      </AppBar>
      <Drawer
        variant="permanent"
        classes={{
          paper: clsx(classes.drawerPaper)
        }}
      >
        <div className={classes.toolbarIcon}>
          <img className={classes.logo} src={logo} alt="Logo" />
        </div>
        <Divider />
        <SideBar></SideBar>
      </Drawer>
      <main className={classes.content}>
        <div className={classes.appBarSpacer} />
        <Container maxWidth="lg" className={classes.container}>
          <ComopnentSwitch></ComopnentSwitch>
        </Container>
        <CreateBackup></CreateBackup>
      </main>
    </div>
  );
}
