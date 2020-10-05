import React from 'react';
import { BrowserRouter, Switch } from 'react-router-dom';
import { useSelector } from 'react-redux';
import SelectKey from '../selectKey/SelectKey';
import WalletAdd from '../wallet/WalletAdd';
import WalletImport from '../wallet/WalletImport';
import PrivateRoute from './PrivateRoute';
import GuestRoute from './GuestRoute';
import Dashboard from '../dashboard/Dashboard';
import { RestoreBackup } from '../../pages/backup/restoreBackup';
import type { RootState } from '../../modules/rootReducer';
import LoadingScreen from '../loading/LoadingScreen';

export default function Router() {
  const loggedInReceived = useSelector(
    (state: RootState) => state.wallet_state.logged_in_received,
  );
  const walletConnected = useSelector(
    (state: RootState) => state.daemon_state.wallet_connected,
  );
  const exiting = useSelector((state: RootState) => state.daemon_state.exiting);

  if (exiting) {
    return <LoadingScreen>Closing down node and server</LoadingScreen>;
  }
  if (!walletConnected) {
    return <LoadingScreen>Connecting to wallet</LoadingScreen>;
  }
  if (!loggedInReceived) {
    return <LoadingScreen>Logging in</LoadingScreen>;
  }

  return (
    <BrowserRouter>
      <Switch>
        <GuestRoute path="/" exact>
          <SelectKey />
        </GuestRoute>
        <GuestRoute path="/wallet/add" exact>
          <WalletAdd />
        </GuestRoute>
        <GuestRoute path="/wallet/import" exact>
          <WalletImport />
        </GuestRoute>
        <PrivateRoute path="/dashboard">
          <Dashboard />
        </PrivateRoute>
      </Switch>
    </BrowserRouter>
  );

  /*
    if (presentView === presentRestoreBackup) {
      return <RestoreBackup></RestoreBackup>;
    }
  }
  */
}
