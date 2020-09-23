import React, { useState } from "react";
import DashboardTitle from '../dashboard/DashboardTitle';
import { Box, Grid, Container, Drawer, List, Divider, ListItem, ListItemText, Typography } from "@material-ui/core";
import { makeStyles } from "@material-ui/core/styles";
import { Redirect } from "react-router-dom";
import { useDispatch, useSelector } from "react-redux";
import clsx from "clsx";
import StandardWallet from "./standard/WalletStandard";
import {
  changeWalletMenu,
  createWallet,
  standardWallet,
  CCWallet,
  RLWallet
} from "../../modules/walletMenu";
import { CreateWalletView } from "./create/WalletCreate";
import ColouredWallet from "./coloured/WalletColoured";
import RateLimitedWallet from "./rateLimited/WalletRateLimited";
import type { RootState } from "../../modules/rootReducer";
import WalletType from '../../types/WalletType';

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
    paddingRight: theme.spacing(0)
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

const WalletItem = (props: any) => {
  const dispatch = useDispatch();
  const id = props.wallet_id;

  const wallet = useSelector((state: RootState) => state.wallet_state.wallets[id]);
  var name = useSelector((state: RootState) => state.wallet_state.wallets[id].name);
  if (!name) {
    name = "";
  }
  var mainLabel = "";
  if (wallet.type === WalletType.STANDARD_WALLET) {
    mainLabel = "Chia Wallet";
    name = "Chia";
  } else if (wallet.type === WalletType.COLOURED_COIN) {
    mainLabel = "CC Wallet";
    if (name.length > 18) {
      name = name.substring(0, 18);
      name = name.concat("...");
    }
  } else if (wallet.type === WalletType.RATE_LIMITED) {
    mainLabel = "RL Wallet";
    if (name.length > 18) {
      name = name.substring(0, 18);
      name = name.concat("...");
    }
  }

  function presentWallet() {
    if (wallet.type === WalletType.STANDARD_WALLET) {
      dispatch(changeWalletMenu(standardWallet, wallet.id));
    } else if (wallet.type === WalletType.COLOURED_COIN) {
      dispatch(changeWalletMenu(CCWallet, wallet.id));
    } else if (wallet.type === WalletType.RATE_LIMITED) {
      dispatch(changeWalletMenu(RLWallet, wallet.id));
    }
  }

  return (
    <ListItem button onClick={presentWallet}>
      <ListItemText primary={mainLabel} secondary={name} />
    </ListItem>
  );
};

const WalletList = () => {
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);

  return (
    <>
      {wallets.map((wallet) => (
        <span key={wallet.id}>
          <WalletItem wallet_id={wallet.id} key={wallet.id}></WalletItem>
          <Divider />
        </span>
      ))}
    </>
  );
};

const WalletViewSwitch = () => {
  const toPresent = useSelector((state: RootState) => state.wallet_menu.view);
  const id = useSelector((state: RootState) => state.wallet_menu.id);

  /*
  if (toPresent === standardWallet) {
    return <StandardWallet wallet_id={id}></StandardWallet>;
  } else if (toPresent === createWallet) {
    return <CreateWalletView></CreateWalletView>;
  } else if (toPresent === CCWallet) {
    return <ColouredWallet wallet_id={id}> </ColouredWallet>;
  } else if (toPresent === RLWallet) {
    return <RateLimitedWallet wallet_id={id}> </RateLimitedWallet>;
  }
  */
  return <div></div>;
};

const CreateWallet = () => {
  const dispatch = useDispatch();
  const classes = useStyles();

  function presentCreateWallet() {
    // dispatch(changeWalletMenu(createWallet));
  }

  return (
    <div className={classes.bottomOptions}>
      <Divider />
      <ListItem button onClick={presentCreateWallet}>
        <ListItemText primary="Add Wallet" />
      </ListItem>
      <Divider />
    </div>
  );
};

export const StatusCard = () => {
  const syncing = useSelector((state: RootState) => state.wallet_state.status.syncing);
  const height = useSelector((state: RootState) => state.wallet_state.status.height);
  const connection_count = useSelector(
    (state: RootState) => state.wallet_state.status.connection_count
  );

  return (
    <div style={{ margin: 16 }}>
      <Typography variant="subtitle1" color="secondary">
        Status
      </Typography>
      <div style={{ marginLeft: 8 }}>
        <Box display="flex">
          <Box flexGrow={1}>status:</Box>
          <Box>{syncing ? "syncing" : "synced"}</Box>
        </Box>
        <Box display="flex">
          <Box flexGrow={1}>height:</Box>
          <Box>{height}</Box>
        </Box>
        <Box display="flex">
          <Box flexGrow={1}>connections:</Box>
          <Box>{connection_count}</Box>
        </Box>
      </div>
    </div>
  );
};

export default function Wallets() {
  const classes = useStyles();
  const logged_in = useSelector((state: RootState) => state.wallet_state.logged_in);

  const [open] = useState(true);
  if (!logged_in) {
    return <Redirect to="/" />;
  }
  return (
    <div className={classes.root}>
      <DashboardTitle>
        Wallets
      </DashboardTitle>
      <Drawer
        variant="permanent"
        classes={{
          paper: clsx(classes.drawerPaper, !open && classes.drawerPaperClose)
        }}
        open={open}
      >
        <Divider />
        <StatusCard />
        <Divider />
        <List>
          <WalletList />
        </List>
        <CreateWallet />
      </Drawer>
      <main className={classes.content}>
        <Container maxWidth="lg" className={classes.container}>
          <Grid container spacing={3}>

            <Grid item xs={12}>
              <WalletViewSwitch></WalletViewSwitch>
            </Grid>
            <Grid item xs={12}></Grid>
          </Grid>
        </Container>
      </main>
    </div>
  );
}
