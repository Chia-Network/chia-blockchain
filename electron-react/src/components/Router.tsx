import React from 'react';
import { HashRouter, Switch, Route } from 'react-router-dom';
import SelectKey from "./selectKey/SelectKey";
import WalletAdd from "./wallet/WalletAdd";
import WalletImport from "./wallet/WalletImport";
import PrivateRoute from './router/PrivateRoute';
import Dashboard from "./dashboard/Dashboard";
// import Dashboard from "../pages/Dashboard";
import { RestoreBackup } from "../pages/backup/restoreBackup";
import { useSelector } from "react-redux";
import {
  presentOldWallet,
  presentNewWallet,
  presentDashboard,
  presentSelectKeys,
  presentRestoreBackup
} from "../modules/entranceMenu";
import type { RootState } from '../modules/rootReducer';
import LoadingScreen from './loading/LoadingScreen';

export default function Router() {
  const loggedInReceived = useSelector(
    (state: RootState) => state.wallet_state.logged_in_received
  );
  const walletConnected = useSelector(
    (state: RootState) => state.daemon_state.wallet_connected
  );
  const exiting = useSelector((state: RootState) => state.daemon_state.exiting);
  const presentView = useSelector((state: RootState) => state.entrance_menu.view);

  if (exiting) {
    return <LoadingScreen>Closing down node and server</LoadingScreen>;
  } else if (!walletConnected) {
    return <LoadingScreen>Connecting to wallet</LoadingScreen>;
  } else if (!loggedInReceived) {
    return <LoadingScreen>Logging in</LoadingScreen>;
  }

  return (
    <HashRouter>
      <Switch>
        <Route path="/" exact>
          <SelectKey />
        </Route>
        <Route path="/wallet/add" exact>
          <WalletAdd />
        </Route>
        <Route path="/wallet/import" exact>
          <WalletImport />
        </Route>
        <PrivateRoute path="/dashboard">
          <Dashboard />
        </PrivateRoute>
      </Switch>
    </HashRouter>
  );

/*
    else if (presentView === presentDashboard) {
      return <Dashboard></Dashboard>;
    } else if (presentView === presentRestoreBackup) {
      return <RestoreBackup></RestoreBackup>;
    }
  }
  */
}
