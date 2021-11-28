import React from 'react';
import { Switch, Route, Redirect } from 'react-router-dom';
import { useSelector } from 'react-redux';
import { Trans } from '@lingui/macro';
import { PrivateRoute, SelectKey } from '@chia/core';
import { WalletAdd, WalletImport } from '@chia/wallets';
import Dashboard from '../dashboard/Dashboard';
import BackupRestore from '../backup/BackupRestore';
import type { RootState } from '../../modules/rootReducer';
import LayoutLoading from '../layout/LayoutLoading';
import AppKeyringMigrator from './AppKeyringMigrator';
import AppPassPrompt from './AppPassPrompt';
import PassphrasePromptReason from '../core/constants/PassphrasePromptReason';

export default function AppRouter() {
/*
  let keyringNeedsMigration = useSelector(
    (state: RootState) => state.keyring_state.needs_migration
  );

  let keyringMigrationSkipped = useSelector(
    (state: RootState) => state.keyring_state.migration_skipped
  );

  let keyringLocked = useSelector(
    (state: RootState) => state.keyring_state.is_locked,
  );

  if (keyringNeedsMigration && !keyringMigrationSkipped) {
    return (
      <AppKeyringMigrator />
    );
  }
  if (keyringLocked) {
    return (
      <LayoutLoading>
        <AppPassPrompt reason={PassphrasePromptReason.KEYRING_LOCKED} />
      </LayoutLoading>
    );
  }
*/

  return (
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
      <Route path="/wallet/restore" exact>
        <BackupRestore />
      </Route>
      <PrivateRoute path="/dashboard">
        <Dashboard />
      </PrivateRoute>
      <Route path="*">
        <Redirect to="/" />
      </Route>
    </Switch>
  );
}
