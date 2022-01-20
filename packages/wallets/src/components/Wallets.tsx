import React from 'react';
import { Trans } from '@lingui/macro';
import { useGetWalletsQuery } from '@chia/api-react';
import StandardWallet from './standard/WalletStandard';
import WalletCreate from './create/WalletCreate';
import WalletCAT from './cat/WalletCAT';
import { CreateOffer } from './offers/OfferManager';
// import RateLimitedWallet from './rateLimited/WalletRateLimited';
// import DistributedWallet from './did/WalletDID';
import { WalletType } from '@chia/api';
import { DashboardTitle, Suspender } from '@chia/core';
import { Routes, Route, Navigate } from 'react-router-dom';
// import WalletsList from './WalletsList';

// <Trans>Loading list of wallets</Trans>}
export default function Wallets() {
  const { data: wallets, isLoading } = useGetWalletsQuery();

  if (isLoading) {
    return (
      <Suspender />
    );
  }

  return (
    <>
      <DashboardTitle><Trans>Wallets</Trans></DashboardTitle>
      <Routes>
        {/*
        <Route element={<WalletsList />} index />
        */}
        <Route path="create/*" element={<WalletCreate />} />
        <Route path="offers/*" element={<CreateOffer />} />
        {!!wallets && (
          <Route path="*" element={<Navigate to="1" />} />
        )}
        {wallets?.map((wallet) => (
          <Route path={wallet.id.toString()} key={wallet.id} element={(
            <>
              {wallet.type === WalletType.STANDARD_WALLET && (
                <StandardWallet walletId={wallet.id} />
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
            </>
          )} />
        ))}
      </Routes>
    </>
  );
}
