import React from 'react';
import { Trans } from '@lingui/macro';
import { WalletType } from '@chia/api';
import { useGetWalletsQuery } from '@chia/api-react';
import { WalletStandard, WalletCAT, WalletCreate } from '@chia/wallets';
import LayoutMain from '../layout/LayoutMain';
import { CreateOffer } from './offers/OfferManager';
import { Switch, Route, useRouteMatch } from 'react-router-dom';

export default function Wallets() {
  const { path } = useRouteMatch();
  const { data: wallets, isLoading } = useGetWalletsQuery();

  return (
    <LayoutMain
      loading={isLoading}
      loadingTitle={<Trans>Loading list of wallets</Trans>}
      title={<Trans>Wallets</Trans>}
    >
      <Switch>
        {wallets?.map((wallet) => (
          <Route path={`${path}/${wallet.id}`} key={wallet.id}>
            {wallet.type === WalletType.STANDARD_WALLET && (
              <WalletStandard walletId={wallet.id} />
            )}

            {wallet.type === WalletType.CAT && (
              <WalletCAT walletId={wallet.id} />
            )}

            {/* wallet.type === WalletType.RATE_LIMITED && (
              <RateLimitedWallet wallet_id={wallet.id} />
            ) */}

            {/* wallet.type === WalletType.DISTRIBUTED_ID && (
              <DistributedWallet walletId={wallet.id} />
            ) */}
          </Route>
        ))}
        <Route path={`/dashboard/wallets/create`}>
          <WalletCreate />
        </Route>
        <Route path={`/dashboard/wallets/offers`}>
          <CreateOffer />
        </Route>
      </Switch>
    </LayoutMain>
  );
}
