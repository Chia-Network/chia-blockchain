import React from 'react';
import { BrowserRouter, Switch } from 'react-router-dom';
import { useSelector } from 'react-redux';
import { Trans } from '@lingui/macro';
import SelectKey from '../selectKey/SelectKey';
import WalletAdd from '../wallet/WalletAdd';
import WalletImport from '../wallet/WalletImport';
import PrivateRoute from './PrivateRoute';
import GuestRoute from './GuestRoute';
import Dashboard from '../dashboard/Dashboard';
import BackupRestore from '../backup/BackupRestore';
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
    return (
      <LoadingScreen>
        <Trans id="Application.closing">Closing down node and server</Trans>
      </LoadingScreen>
    );
  }
  if (!walletConnected) {
    return (
      <LoadingScreen>
        <Trans id="Application.connectingToWallet">Connecting to wallet</Trans>
      </LoadingScreen>
    );
  }
  if (!loggedInReceived) {
    return (
      <LoadingScreen>
        <Trans id="Application.loggingIn">Logging in</Trans>
      </LoadingScreen>
    );
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
        <GuestRoute path="/wallet/restore" exact>
          <BackupRestore />
        </GuestRoute>
        <PrivateRoute path="/dashboard">
          <Dashboard />
        </PrivateRoute>
      </Switch>
    </BrowserRouter>
  );
}
