import React /* , { ReactNode } */ from 'react';
import { Trans } from '@lingui/macro';
import { Flex, ConfirmDialog } from '@chia/core';
import { useDispatch } from 'react-redux';
import WalletHistory from '../WalletHistory';
import { deleteUnconfirmedTransactions } from '../../../modules/incoming';
import WalletStandardCards from './WalletStandardCards';
import useOpenDialog from '../../../hooks/useOpenDialog';
import WalletReceiveAddress from '../WalletReceiveAddress';
import WalletSend from '../WalletSend';
import WalletHeader from '../WalletHeader';

type StandardWalletProps = {
  walletId: number;
};

export default function StandardWallet(props: StandardWalletProps) {
  const { walletId } = props;

  return (
    <Flex flexDirection="column" gap={1}>
      <WalletHeader
        walletId={walletId}
        title={<Trans>Chia Wallet</Trans>}
      />

      <Flex flexDirection="column" gap={3}>
        <WalletStandardCards walletId={walletId} />
        <WalletReceiveAddress walletId={walletId} />
        <WalletSend wallet_id={walletId} />
        <WalletHistory walletId={walletId} />
      </Flex>
    </Flex>
  );
}
