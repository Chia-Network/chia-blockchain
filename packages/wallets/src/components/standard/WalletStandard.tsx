import React, { useState } from 'react';
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
  // const showDebugInformation = useShowDebugInformation();
  const [selectedTab, setSelectedTab] = useState<'summary' | 'send' | 'receive'>('summary');

  return (
    <Flex flexDirection="column" gap={2.5}>
      <WalletHeader
        walletId={walletId}
        tab={selectedTab}
        onTabChange={setSelectedTab}
      />

      {selectedTab === 'summary' && (
        <Flex flexDirection="column" gap={4}>
          <WalletStandardCards walletId={walletId} />
          <WalletHistory walletId={walletId} />
        </Flex>
      )}
      {selectedTab === 'send' && (
        <WalletSend walletId={walletId} />
      )}
      {selectedTab === 'receive' && (
        <WalletReceiveAddress walletId={walletId} />
      )}

      {/*
      {showDebugInformation && (
        <WalletConnections walletId={walletId} />
      )}
      */}
    </Flex>
  );
}
