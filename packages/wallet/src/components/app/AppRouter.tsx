import React from 'react';
import { Switch, Route, Redirect } from 'react-router-dom';
import { PrivateRoute, SelectKey } from '@chia/core';
import { WalletAdd, WalletImport } from '@chia/wallets';
import Dashboard from '../dashboard/Dashboard';
import { defaultLocale, locales } from '../../config/locales';

export default function AppRouter() {
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
      {/*
      <Route path="/wallet/restore" exact>
        <BackupRestore />
      </Route>
      */}
      <PrivateRoute path="/dashboard">
        <Dashboard />
      </PrivateRoute>
      <Route path="*">
        <Redirect to="/" />
      </Route>
    </Switch>
  );
}
