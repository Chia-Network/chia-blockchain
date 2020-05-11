import React from 'react';
import CssBaseline from '@material-ui/core/CssBaseline';
import Grid from '@material-ui/core/Grid';
import { makeStyles } from '@material-ui/core/styles';
import Container from '@material-ui/core/Container';
import { withRouter, Redirect } from 'react-router-dom'
import { connect, useDispatch, useSelector } from 'react-redux';
import { log_out } from '../modules/message';
import clsx from 'clsx';
import Drawer from '@material-ui/core/Drawer';
import List from '@material-ui/core/List';
import Typography from '@material-ui/core/Typography';
import Divider from '@material-ui/core/Divider';
import ListItem from '@material-ui/core/ListItem';
import ListItemIcon from '@material-ui/core/ListItemIcon';
import ListItemText from '@material-ui/core/ListItemText';
import ListSubheader from '@material-ui/core/ListSubheader';
import DashboardIcon from '@material-ui/icons/Dashboard';
import Paper from '@material-ui/core/Paper';
import StandardWallet from './StandardWallet';
import Box from '@material-ui/core/Box';
import { changeWalletMenu, createWallet, standardWallet, tradeManager, CCWallet} from '../modules/walletMenu';
import { CreateWalletView } from './CreateWallet';
import ColouredWallet from './ColouredWallet';

const drawerWidth = 180;

const useStyles = makeStyles((theme) => ({
  root: {
    display: 'flex',
    paddingLeft: '0px'
  },
  toolbar: {
    paddingRight: 24, // keep right padding when drawer closed
  },
  toolbarIcon: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'flex-end',
    padding: '0 8px',
    ...theme.mixins.toolbar,
  },
  appBar: {
    zIndex: theme.zIndex.drawer + 1,
    transition: theme.transitions.create(['width', 'margin'], {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.leavingScreen,
    }),
  },
  appBarShift: {
    marginLeft: drawerWidth,
    width: `calc(100% - ${drawerWidth}px)`,
    transition: theme.transitions.create(['width', 'margin'], {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.enteringScreen,
    }),
  },
  menuButton: {
    marginRight: 36,
  },
  menuButtonHidden: {
    display: 'none',
  },
  title: {
    flexGrow: 1,
  },
  drawerPaper: {
    position: 'relative',
    whiteSpace: 'nowrap',
    width: drawerWidth,
    transition: theme.transitions.create('width', {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.enteringScreen,
    }),
  },
  drawerPaperClose: {
    overflowX: 'hidden',
    transition: theme.transitions.create('width', {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.leavingScreen,
    }),
    width: theme.spacing(7),
    [theme.breakpoints.up('sm')]: {
      width: theme.spacing(9),
    },
  },
  appBarSpacer: theme.mixins.toolbar,
  content: {
    flexGrow: 1,
    height: '100vh',
    overflowX: 'hidden',
  },
  container: {
    paddingTop: theme.spacing(0),
    paddingBottom: theme.spacing(0),
    paddingRight: theme.spacing(0),
  },
  paper: {
    padding: theme.spacing(0),
    display: 'flex',
    overflow: 'auto',
    flexDirection: 'column',
  },
  fixedHeight: {
    height: 240,
  },
  drawerWallet: {
    position: 'relative',
    whiteSpace: 'nowrap',
    width: drawerWidth,
    height: '100%',
    transition: theme.transitions.create('width', {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.enteringScreen,
    }),
  },
  balancePaper: {
    height: 200,
    marginTop: theme.spacing(2),
  }
}));

const WalletItem = (props) => {
  const dispatch = useDispatch()
  const id = props.wallet_id

  const wallet = useSelector(state => state.wallet_state.wallets[id])
  var name = useSelector(state => state.wallet_state.wallets[id].name)

  var mainLabel = ""
  if (wallet.type === "STANDARD_WALLET") {
    var mainLabel = "Chia Wallet"
    name = "Chia"
  } else if (wallet.type == "COLOURED_COIN") {
    var mainLabel = "CC Wallet"
    if (name.length > 18) {
      name = name.substring(0,18);
      name = name.concat("...")
    }
  }

  function presentWallet() {
      console.log(wallet)
      if (wallet.type === "STANDARD_WALLET") {
        dispatch(changeWalletMenu(standardWallet, wallet.id))
      } else if (wallet.type == "COLOURED_COIN") {
        dispatch(changeWalletMenu(CCWallet, wallet.id))
      }
  }

  return (
    <ListItem button onClick={presentWallet}>
        <ListItemText primary={mainLabel} secondary={name}/>
    </ListItem>
  )
}

const WalletList = () => {
  const wallets = useSelector(state => state.wallet_state.wallets)

  return wallets.map((wallet) =>
    <WalletItem wallet_id={wallet.id}></WalletItem>
  )
}

const WalletViewSwitch = () => {
  const toPresent = useSelector(state => state.wallet_menu.view)
  const id = useSelector(state => state.wallet_menu.id)

  if (toPresent === standardWallet) {
    return(
      <StandardWallet wallet_id={id} ></StandardWallet>
    )
  } else if (toPresent == createWallet) {
    return (
      <CreateWalletView></CreateWalletView>
    )
  } else if (toPresent == tradeManager) {
    return (
      <div>Trade Manager</div>
    )
  } else if (toPresent == CCWallet) {
    return (
      <ColouredWallet wallet_id={id}>  </ColouredWallet>
    )
  }
  return (
    <div></div>
  )
}

const CreateWallet = () => {
  const dispatch = useDispatch()

  function presentCreateWallet() {
      dispatch(changeWalletMenu(createWallet))
  }

  return (
    <ListItem button onClick={presentCreateWallet}>
      <ListItemText primary="Add Wallet" />
    </ListItem>)
}

export const StatusCard = () => {
  const syncing = useSelector(state => state.wallet_state.status.syncing)
  const height = useSelector(state => state.wallet_state.status.height)
  const connection_count = useSelector(state => state.wallet_state.status.connection_count)

  return (
    <div style={{ margin: 16 }}>
      <Typography component="subtitle1" variant="subtitle1" color="secondary">
        Status
      </Typography>
      <div style={{marginLeft: 8}}>
      <Box display="flex">
        <Box flexGrow={1} >
          status:
        </Box>
        <Box>
          {syncing ? "syncing" : "synced"}
        </Box>
      </Box>
      <Box display="flex">
        <Box flexGrow={1} >
          height:
        </Box>
        <Box>
          {height}
        </Box>
      </Box>
      <Box display="flex">
        <Box flexGrow={1} >
          connections:
        </Box>
        <Box>
          {connection_count}
        </Box>
      </Box>
      </div>
    </div>
  )
}

const Wallets = () => {
  const classes = useStyles();
  const dispatch = useDispatch()
  const logged_in = useSelector(state => state.wallet_state.logged_in)

  const [open, setOpen] = React.useState(true);
  const handleDrawerOpen = () => {
    setOpen(true);
  };
  const handleDrawerClose = () => {
    setOpen(false);
  };
  const fixedHeightPaper = clsx(classes.paper, classes.fixedHeight);
  function log_out_click() {
    dispatch(log_out())
  }
  if (!logged_in) {
    console.log("Redirecting to start")
    return (<Redirect to="/" />)
  }
  return (
    <div className={classes.root}>
      <CssBaseline />
      <Drawer
        variant="permanent"
        classes={{
          paper: clsx(classes.drawerPaper, !open && classes.drawerPaperClose),
        }}
        open={open}
      >
        <Divider />
        <StatusCard></StatusCard>
        <Divider />
        <List>
          <WalletList></WalletList>
          <Divider />
          <CreateWallet></CreateWallet>
        </List>
      </Drawer>
      <main className={classes.content}>
        <Container maxWidth="lg" className={classes.container}>
          <Grid container spacing={3}>
            {/* Chart */}
            <Grid item xs={12}>
              <WalletViewSwitch></WalletViewSwitch>
            </Grid>
            <Grid item xs={12}>
            </Grid>
          </Grid>
        </Container>
      </main>
    </div>
  );
}

export default withRouter(connect()(Wallets));
