import React, { useState, type ReactNode } from 'react';
import { Trans } from '@lingui/macro';
import {
  Button,
  Flex,
  ConfirmDialog,
  useOpenDialog,
  useShowDebugInformation,
  AlertDialog,
  DropdownActions,
} from '@chia/core';
import { useNavigate } from 'react-router';
import {
  Box,
  Typography,
  ListItemIcon,
  MenuItem,
  Tab,
  Tabs,
  TabPanel,
} from '@mui/material';
import {
  Delete as DeleteIcon,
} from '@mui/icons-material';
import { useDeleteUnconfirmedTransactionsMutation, useGetSyncStatusQuery } from '@chia/api-react';
import WalletName from './WalletName';

type StandardWalletProps = {
  walletId: number;
  actions?: ({ onClose } : { onClose: () => void } ) => ReactNode;
  tab: 'summary' | 'send' | 'receive';
  onTabChange: (tab: 'summary' | 'send' | 'receive') => void;
};

export default function WalletHeader(props: StandardWalletProps) {
  const { walletId, actions, tab, onTabChange } = props;
  const openDialog = useOpenDialog();
  const { data: walletState, isLoading: isWalletSyncLoading } = useGetSyncStatusQuery();
  const showDebugInformation = useShowDebugInformation();
  const [deleteUnconfirmedTransactions] = useDeleteUnconfirmedTransactionsMutation();
  const navigate = useNavigate();

  async function handleDeleteUnconfirmedTransactions() {
    await openDialog(
      <ConfirmDialog
        title={<Trans>Confirmation</Trans>}
        confirmTitle={<Trans>Delete</Trans>}
        confirmColor="danger"
        onConfirm={() => deleteUnconfirmedTransactions({ walletId }).unwrap()}
      >
        <Trans>Are you sure you want to delete unconfirmed transactions?</Trans>
      </ConfirmDialog>,
    );
  }

  function handleAddToken() {
    navigate('/dashboard/wallets/create/simple');
  }

  async function handleManageOffers() {
    if (isWalletSyncLoading || walletState.syncing) {
      await openDialog(
        <AlertDialog>
          <Trans>Please finish syncing before managing offers</Trans>
        </AlertDialog>,
      );
      return;
    }
    else {
      navigate('/dashboard/offers/manage');
    }
  }

  return (
    <Flex flexDirection="column">
      <WalletName walletId={walletId} variant="h5" />
      <Flex gap={1} alignItems="center">
        <Flex flexGrow={1} gap={1}>
          <Tabs
            value={tab}
            onChange={(_event, newValue) => onTabChange(newValue)}
            textColor="primary"
            indicatorColor="primary"
          >
            <Tab value="summary" label={<Trans>Summary</Trans>} />
            <Tab value="send" label={<Trans>Send</Trans>} />
            <Tab value="receive" label={<Trans>Receive</Trans>} />
          </Tabs>
        </Flex>
        <Flex gap={1} alignItems="center">
          {/*
          <Flex alignItems="center">
            <Typography variant="body1" color="textSecondary">
              <Trans>Status:</Trans>
            </Typography>
            &nbsp;
            <WalletStatus height={showDebugInformation} />
          </Flex>
          */}

          <DropdownActions label={<Trans>Actions</Trans>}>
            {({ onClose }) => (
              <>
                <MenuItem
                  onClick={() => {
                    onClose();
                    handleDeleteUnconfirmedTransactions();
                  }}
                >
                  <ListItemIcon>
                    <DeleteIcon />
                  </ListItemIcon>
                  <Typography variant="inherit" noWrap>
                    <Trans>Delete Unconfirmed Transactions</Trans>
                  </Typography>
                </MenuItem>
                {actions?.({ onClose })}
              </>
            )}
          </DropdownActions>
        </Flex>
      </Flex>
    </Flex>
  );
}
