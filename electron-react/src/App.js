import React from "react";
import SelectKey from "./pages/SelectKey";
import NewWallet from "./pages/NewWallet";
import OldWallet from "./pages/OldWallet";
import Dashboard from "./pages/Dashboard";
import { connect, useSelector } from "react-redux";

import { ThemeProvider } from "@material-ui/core/styles";
import {
  presentOldWallet,
  presentNewWallet,
  presentDashboard,
  presentSelectKeys,
  presentRestoreBackup
} from "./modules/entranceMenu";
import { Backdrop, CircularProgress } from "@material-ui/core";
import { ModalDialog, Spinner } from "./pages/ModalDialog";
import { RestoreBackup } from "./pages/backup/restoreBackup";

import theme from "./muiTheme";

const LoadingScreen = () => {
  return (
    <Backdrop open={true} invisible={false}>
      <CircularProgress color="inherit" />
    </Backdrop>
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
  const presentView = useSelector(state => state.entrance_menu.view);
  if (!wallet_connected) {
    return <LoadingScreen></LoadingScreen>;
  } else if (!logged_in_received) {
    return <LoadingScreen></LoadingScreen>;
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
