import { Alert } from '@mui/material';
import { useParams } from 'react-router-dom';
import { Trans } from '@lingui/macro';
import { Suspender } from '@chia/core';
import { WalletType } from '@chia/api';
import React from 'react';
import WalletStandard from './standard/WalletStandard';
import WalletCAT from './cat/WalletCAT';
import useWallet from '../hooks/useWallet';

export default function Wallet() {
  const { walletId } = useParams();
  const { wallet, loading } = useWallet(walletId);
  if (loading) {
    return (
      <Suspender />
    );
  }

  if (!wallet) {
    return (
      <Alert severity="warning">
        <Trans>Wallet {walletId} not found</Trans>
      </Alert>
    );
  }

  if (wallet.type === WalletType.STANDARD_WALLET) {
    return (
      <WalletStandard walletId={Number(walletId)} />
    );
  }

  if (wallet.type === WalletType.CAT) {
    return (
      <WalletCAT walletId={Number(walletId)} />
    );
  }

  {/* wallet.type === WalletType.RATE_LIMITED && (
    <RateLimitedWallet wallet_id={wallet.id} />
  ) */}

  {/* wallet.type === WalletType.DECENTRALIZED_ID && (
    <DistributedWallet walletId={wallet.id} />
  ) */}

  return (
    <Alert severity="warning">
      <Trans>Wallet with type {wallet.type} not supported</Trans>
    </Alert>
  );
}
