import React from 'react';
import { Switch, Route, useRouteMatch } from 'react-router-dom';
import WalletCATSelect from './WalletCATSelect';
import WalletCATCreateNew from './WalletCATCreateNew';
import WalletCATCreateExisting from './WalletCATCreateExisting';

export default function WalletCATList() {
  const { path } = useRouteMatch();

  return (
    <Switch>
      <Route path={path} exact>
        <WalletCATSelect />
      </Route>
      <Route path={`${path}/create`} exact>
        <WalletCATCreateNew />
      </Route>
      <Route path={`${path}/existing`} exact>
        <WalletCATCreateExisting />
      </Route>
    </Switch>
  );
}
