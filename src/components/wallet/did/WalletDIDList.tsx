import React from 'react';
import { Switch, Route, useRouteMatch } from 'react-router-dom';
import WalletDIDSelect from './WalletDIDSelect';
import WalletDIDCreate from './WalletDIDCreate';
import WalletDIDRecovery from './WalletDIDRecovery';

export default function WalletDIDList() {
  const { path } = useRouteMatch();

  return (
    <Switch>
      <Route path={path} exact>
        <WalletDIDSelect />
      </Route>
      <Route path={`${path}/create`} exact>
        <WalletDIDCreate />
      </Route>
      <Route path={`${path}/recovery`} exact>
        <WalletDIDRecovery />
      </Route>
    </Switch>
  );
}
