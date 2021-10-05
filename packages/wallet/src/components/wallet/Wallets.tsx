import React from 'react';
import { Trans } from '@lingui/macro';
import {  useSelector } from 'react-redux';
import StandardWallet from './standard/WalletStandard';
import { CreateWalletView } from './create/WalletCreate';
import WalletCAT from './cat/WalletCAT';
import RateLimitedWallet from './rateLimited/WalletRateLimited';
import DistributedWallet from './did/WalletDID';
import type { RootState } from '../../modules/rootReducer';
import WalletType from '../../constants/WalletType';
import LayoutMain from '../layout/LayoutMain';
import { Switch, Route, useRouteMatch } from 'react-router-dom';
import WalletsList from './WalletsList';

export default function Wallets() {
  const { path } = useRouteMatch();
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);
  const loading = !wallets;

  return (
    <LayoutMain
      loading={loading}
      loadingTitle={<Trans>Loading list of wallets</Trans>}
      title={<Trans>Wallets</Trans>}
    >
      <Switch>
        <Route path="/dashboard/wallets" exact>
          <WalletsList />
        </Route>
        {wallets?.map((wallet) => (
          <Route path={`${path}/${wallet.id}`} key={wallet.id}>
            {wallet.type === WalletType.STANDARD_WALLET && (
              <StandardWallet walletId={wallet.id} />
            )}

            {wallet.type === WalletType.CAT && (
              <WalletCAT walletId={wallet.id} />
            )}

            {wallet.type === WalletType.RATE_LIMITED && (
              <RateLimitedWallet wallet_id={wallet.id} />
            )}

            {wallet.type === WalletType.DISTRIBUTED_ID && (
              <DistributedWallet walletId={wallet.id} />
            )}
          </Route>
        ))}
        <Route path={`/dashboard/wallets/create`}>
          <CreateWalletView />
        </Route>
      </Switch>
    </LayoutMain>
  );
}
