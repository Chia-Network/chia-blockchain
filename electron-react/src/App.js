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
import { Backdrop, CircularProgress } from "@material-ui/core";
import { ModalDialog, Spinner } from "./pages/ModalDialog";
import { RestoreBackup } from "./pages/backup/restoreBackup";
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
