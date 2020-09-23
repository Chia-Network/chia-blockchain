import React from "react";
import Grid from "@material-ui/core/Grid";
import { makeStyles } from "@material-ui/core/styles";
import Container from "@material-ui/core/Container";
import { useDispatch, useSelector } from "react-redux";
import clsx from "clsx";
import Drawer from "@material-ui/core/Drawer";
import List from "@material-ui/core/List";
import Divider from "@material-ui/core/Divider";
import ListItem from "@material-ui/core/ListItem";
import ListItemText from "@material-ui/core/ListItemText";
import {
  tradingOverview,
  createTrades,
  changeTradeMenu,
  viewTrades
} from "../../modules/tradeMenu";
import { OfferSwitch } from "./ViewOffer";
import { TradingOverview } from "./TradingOverview";
import { CreateOffer } from "./CreateOffer";
import DashboardTitle from '../dashboard/DashboardTitle';

const drawerWidth = 180;

const useStyles = makeStyles(theme => ({
  root: {
    display: "flex",
    paddingLeft: "0px"
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
  drawerPaperClose: {
    overflowX: "hidden",
    transition: theme.transitions.create("width", {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.leavingScreen
    }),
    width: theme.spacing(7),
    [theme.breakpoints.up("sm")]: {
      width: theme.spacing(9)
    }
  },
  content: {
    flexGrow: 1,
    height: "calc(100vh - 64px)",
    overflowX: "hidden"
  },
  container: {
    paddingTop: theme.spacing(0),
    paddingBottom: theme.spacing(0),
    paddingRight: theme.spacing(0),
    paddingLeft: theme.spacing(0)
  },
  paper: {
    padding: theme.spacing(0),
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
  balancePaper: {
    height: 200,
    marginTop: theme.spacing(2)
  },
  bottomOptions: {
    position: "absolute",
    bottom: 0,
    width: "100%"
  }
}));

const TradeList = () => {
  const dispatch = useDispatch();
  function view_trade() {
    dispatch(changeTradeMenu(viewTrades));
  }

  function create_trade() {
    dispatch(changeTradeMenu(createTrades));
  }

  function trade_overview() {
    dispatch(changeTradeMenu(tradingOverview));
  }
  return (
    <List>
      <span key={"trade_overview"}>
        <ListItem button onClick={trade_overview}>
          <ListItemText primary="Trade Overview" secondary={""} />
        </ListItem>
      </span>
      <Divider></Divider>
      <ListItem button onClick={create_trade}>
        <ListItemText primary={"Create Trade"} secondary={""} />
      </ListItem>
      <Divider></Divider>

      <ListItem button onClick={view_trade}>
        <ListItemText primary={"View Trade"} secondary={""} />
      </ListItem>
      <Divider></Divider>
    </List>
  );
};

const TradeViewSwitch = () => {
  const toPresent = useSelector(state => state.trade_menu.view);

  if (toPresent === tradingOverview) {
    return <TradingOverview></TradingOverview>;
  } else if (toPresent === createTrades) {
    return <CreateOffer></CreateOffer>;
  } else if (toPresent === viewTrades) {
    return <OfferSwitch></OfferSwitch>;
  }
  return <div></div>;
};

export const TradeManger = () => {
  const classes = useStyles();
  const [open] = React.useState(true);

  return (
    <div className={classes.root}>
      <DashboardTitle>
        Trading
      </DashboardTitle>
      <Drawer
        variant="permanent"
        classes={{
          paper: clsx(classes.drawerPaper, !open && classes.drawerPaperClose)
        }}
        open={open}
      >
        <TradeList></TradeList>
      </Drawer>
      <main className={classes.content}>
        <Container maxWidth="lg" className={classes.container}>
          <Grid container spacing={3}>
            {/* Chart */}
            <Grid item xs={12}>
              <TradeViewSwitch></TradeViewSwitch>
            </Grid>
            <Grid item xs={12}></Grid>
          </Grid>
        </Container>
      </main>
    </div>
  );
};
