import React from 'react';
import { HashRouter, Switch, Route } from 'react-router-dom';
import SelectKey from "./selectKey/SelectKey";
import WalletAdd from "./wallet/WalletAdd";
import WalletImport from "./wallet/WalletImport";
import Dashboard from "../pages/Dashboard";
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
  const logged_in = useSelector((state: RootState) => state.wallet_state.logged_in);
  const logged_in_received = useSelector(
    (state: RootState) => state.wallet_state.logged_in_received
  );
  const wallet_connected = useSelector(
    (state: RootState) => state.daemon_state.wallet_connected
  );
  const exiting = useSelector((state: RootState) => state.daemon_state.exiting);
  const presentView = useSelector((state: RootState) => state.entrance_menu.view);
  if (exiting) {
    return <LoadingScreen>Closing down node and server</LoadingScreen>;
  } else if (!wallet_connected) {
    return <LoadingScreen>Connecting to wallet</LoadingScreen>;
  } else if (!logged_in_received) {
    return <LoadingScreen>Logging in</LoadingScreen>;
  } else if (logged_in) {
    return <Dashboard></Dashboard>;
  } 

  console.log('presentView', presentView);

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
