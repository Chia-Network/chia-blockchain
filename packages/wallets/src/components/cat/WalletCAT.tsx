import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import { Card, CopyToClipboard, Flex, Loading, useOpenDialog } from '@chia/core';
import { Alert, InputAdornment, Typography } from '@mui/material';
import { Edit as RenameIcon, Fingerprint as FingerprintIcon } from '@mui/icons-material';
import {
  Box,
  TextField,
  ListItemIcon,
  MenuItem,
} from '@mui/material';
import { useSetCATNameMutation, useGetCatListQuery } from '@chia/api-react';
import WalletHistory from '../WalletHistory';
import useWallet from '../../hooks/useWallet';
import WalletReceiveAddress from '../WalletReceiveAddress';
import WalletCards from '../WalletCards';
import WalletCATSend from './WalletCATSend';
import WalletHeader from '../WalletHeader';
import WalletRenameDialog from '../WalletRenameDialog';
import WalletCATTAILDialog from './WalletCATTAILDialog';

type Props = {
  walletId: number;
};

export default function WalletCAT(props: Props) {
  const { walletId } = props;
  const { wallet, loading } = useWallet(walletId);
  const { data: catList = [], isLoading: isCatListLoading } = useGetCatListQuery();
  const openDialog = useOpenDialog();
  const [setCATName] = useSetCATNameMutation();
  const [selectedTab, setSelectedTab] = useState<'summary' | 'send' | 'receive'>('summary');

  function handleRename() {
    if (!wallet) {
      return;
    }

    const { name } = wallet;

    openDialog((
      <WalletRenameDialog
        name={name}
        onSave={(newName) => setCATName({ walletId, name: newName}).unwrap()}
      />
    ));
  }

  function handleShowTAIL() {
    openDialog((
      <WalletCATTAILDialog walletId={walletId} />
    ));
  }

  if (loading || isCatListLoading) {
    return (
      <Loading center />
    );
  }

  if (!wallet) {
    return (
      <Alert severity="error">
        <Trans>Wallet does not exists</Trans>
      </Alert>
    );
  }

  const token = catList.find((item) => item.assetId === wallet.meta?.assetId);
  const canRename = !token;

  return (
    <Flex flexDirection="column" gap={2}>
      <WalletHeader
        walletId={walletId}
        tab={selectedTab}
        onTabChange={setSelectedTab}
        actions={({ onClose }) => (
          <>
            {canRename && (
              <MenuItem
                onClick={() => {
                  onClose();
                  handleRename();
                }}
              >
                <ListItemIcon>
                  <RenameIcon />
                </ListItemIcon>
                <Typography variant="inherit" noWrap>
                  <Trans>Rename Wallet</Trans>
                </Typography>
              </MenuItem>
            )}
            <MenuItem
              onClick={() => {
                onClose();
                handleShowTAIL();
              }}
            >
              <ListItemIcon>
                <FingerprintIcon />
              </ListItemIcon>
              <Typography variant="inherit" noWrap>
                <Trans>Show Asset Id</Trans>
              </Typography>
            </MenuItem>
          </>
        )}
      />
      {selectedTab === 'summary' && (
        <Flex flexDirection="column" gap={4}>
          <WalletCards walletId={walletId} />
          <WalletHistory walletId={walletId} />
        </Flex>
      )}
      {selectedTab === 'send' && (
        <WalletCATSend walletId={walletId} />
      )}
      {selectedTab === 'receive' && (
        <WalletReceiveAddress walletId={walletId} />
      )}
    </Flex>
  );
}
