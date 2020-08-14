import React from "react";
import SelectKey from "./pages/SelectKey";
import NewWallet from "./pages/NewWallet";
import OldWallet from "./pages/OldWallet";
import Dashboard from "./pages/Dashboard";
import { connect, useSelector } from "react-redux";

import { createMuiTheme, ThemeProvider } from "@material-ui/core/styles";
import {
  presentOldWallet,
  presentNewWallet,
  presentDashboard,
  presentSelectKeys,
  presentRestoreBackup
} from "./modules/entranceMenu";
import { CircularProgress } from "@material-ui/core";
import { ModalDialog, Spinner } from "./pages/ModalDialog";
import { RestoreBackup } from "./pages/backup/restoreBackup";
import { makeStyles } from "@material-ui/core/styles";
const defaultTheme = createMuiTheme();

const theme = createMuiTheme({
  palette: {
    primary: { main: "#ffffff", contrastText: "#000000" },
    secondary: { main: "#000000", contrastText: "#ffffff" }
  },
  root: {
    background: "linear-gradient(45deg, #333333 30%, #333333 90%)",
    height: "100%"
  },
  app_root: {
    background: "linear-gradient(45deg, #142229 30%, #112240 90%)",
    height: "100%"
  },
  paper: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center"
  },
  avatar: {
    marginTop: defaultTheme.spacing(8),
    backgroundColor: defaultTheme.palette.secondary.main
  },
  form: {
    width: "100%",
    marginTop: defaultTheme.spacing(5)
  },
  textField: {
    borderColor: "#ffffff"
  },
  submit: {
    marginTop: defaultTheme.spacing(8),
    marginBottom: defaultTheme.spacing(3)
  },
  grid: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    paddingTop: defaultTheme.spacing(5)
  },
  grid_item: {
    paddingTop: 10,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    backgroundColor: "#444444",
    color: "#ffffff",
    height: 50,
    verticalAlign: "middle"
  },
  title: {
    color: "#ffffff",
    marginTop: defaultTheme.spacing(4),
    marginBottom: defaultTheme.spacing(8)
  },
  navigator: {
    color: "#ffffff",
    marginTop: defaultTheme.spacing(4),
    marginLeft: defaultTheme.spacing(4),
    fontSize: 35
  }
});
const styles = theme => ({
  div: {
    height: "100%",
    background: "linear-gradient(45deg, #222222 30%, #333333 90%)",
    fontFamily: "Open Sans, sans-serif"
  },
  center: {
    textAlign: "center",
    height: "200px",
    width: "300px",
    position: "absolute",
    top: 0,
    bottom: 0,
    left: 0,
    right: 0,
    margin: "auto"
  },
  h3: {
    color: "white"
  }
});

const useStyles = makeStyles(styles);
const LoadingScreen = props => {
  const classes = useStyles();
  return (
    <div className={classes.div}>
      <div className={classes.center}>
        <h3 className={classes.h3}>{props.children}</h3>
        <CircularProgress className={classes.h3} />
      </div>
    </div>
  );
};

const CustomRouter = () => {
  const logged_in = useSelector(state => state.wallet_state.logged_in);
  const logged_in_received = useSelector(
    state => state.wallet_state.logged_in_received
  );
  const wallet_connected = useSelector(
    state => state.daemon_state.wallet_connected
  );
  const exiting = useSelector(state => state.daemon_state.exiting);
  const presentView = useSelector(state => state.entrance_menu.view);
  if (exiting) {
    return <LoadingScreen>Closing down node and server</LoadingScreen>;
  } else if (!wallet_connected) {
    return <LoadingScreen>Connecting to wallet</LoadingScreen>;
  } else if (!logged_in_received) {
    return <LoadingScreen>Logging in</LoadingScreen>;
  } else if (logged_in) {
    return <Dashboard></Dashboard>;
  } else {
    if (presentView === presentSelectKeys) {
      return <SelectKey></SelectKey>;
    } else if (presentView === presentOldWallet) {
      return <OldWallet></OldWallet>;
    } else if (presentView === presentNewWallet) {
      return <NewWallet></NewWallet>;
    } else if (presentView === presentDashboard) {
      return <Dashboard></Dashboard>;
    } else if (presentView === presentRestoreBackup) {
      return <RestoreBackup></RestoreBackup>;
    }
  }
};
const App = () => {
  return (
    <React.Fragment>
      <ThemeProvider theme={theme}>
        <ModalDialog></ModalDialog>
        <Spinner></Spinner>
        <CustomRouter></CustomRouter>
      </ThemeProvider>
    </React.Fragment>
  );
};

export default connect()(App);
