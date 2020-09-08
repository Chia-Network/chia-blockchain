import React from "react";
import SelectKey from "./pages/SelectKey";
import NewWallet from "./pages/NewWallet";
import OldWallet from "./pages/OldWallet";
import Dashboard from "./pages/Dashboard";
import { useSelector } from "react-redux";

import { ThemeProvider } from "@material-ui/core/styles";
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

import theme from "./muiTheme";

const LoadingScreen = props => {
  const classes = theme;
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

export default App;
