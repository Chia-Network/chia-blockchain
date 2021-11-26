import React from 'react';
import { Switch, Route, Redirect } from 'react-router-dom';
import { PrivateRoute } from '@chia/core';
import SelectKey from '../selectKey/SelectKey';
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
        <WalletAdd locales={locales} defaultLocale={defaultLocale} />
      </Route>
      <Route path="/wallet/import" exact>
        <WalletImport locales={locales} defaultLocale={defaultLocale} />
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
