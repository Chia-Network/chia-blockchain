import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import { useShowDebugInformation, Flex } from '@chia/core';
import { Tab, Tabs } from '@mui/material';
import WalletHistory from '../WalletHistory';
import WalletStandardCards from './WalletStandardCards';
import WalletReceiveAddress from '../WalletReceiveAddress';
import WalletSend from '../WalletSend';
import WalletHeader from '../WalletHeader';
import WalletConnections from '../WalletConnections';
import { values } from 'lodash';

type StandardWalletProps = {
  walletId: number;
};

export default function StandardWallet(props: StandardWalletProps) {
  const { walletId } = props;
  const showDebugInformation = useShowDebugInformation();
  const [selectedTab, setSelectedTab] = useState<'summary' | 'send' | 'receive'>('summary');

  return (
    <Flex flexDirection="column" gap={2}>
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
