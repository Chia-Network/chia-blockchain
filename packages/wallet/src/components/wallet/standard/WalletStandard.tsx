import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex } from '@chia/core';
import WalletHistory from '../WalletHistory';
import WalletStandardCards from './WalletStandardCards';
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
        <WalletSend walletId={walletId} />
        <WalletHistory walletId={walletId} />
      </Flex>
    </Flex>
  );
}
