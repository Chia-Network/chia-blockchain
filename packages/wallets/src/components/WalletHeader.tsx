import React, { ReactNode } from 'react';
import { Trans } from '@lingui/macro';
import {
  More,
  Flex,
  ConfirmDialog,
  useOpenDialog,
  useShowDebugInformation,
  AlertDialog,
} from '@chia/core';
import { useNavigate } from 'react-router';
import {
  Box,
  Typography,
  ListItemIcon,
  MenuItem,
  Button,
} from '@material-ui/core';
import {
  Delete as DeleteIcon,
} from '@material-ui/icons';
import { useDeleteUnconfirmedTransactionsMutation, useGetSyncStatusQuery } from '@chia/api-react';
import WalletStatus from './WalletStatus';
import WalletsDropdodown from './WalletsDropdown';

type StandardWalletProps = {
  walletId: number;
  actions?: ({ onClose } : { onClose: () => void } ) => ReactNode;
};

export default function WalletHeader(props: StandardWalletProps) {
  const { walletId, actions } = props;
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
      navigate('/dashboard/wallets/offers/manage');
    }
  }

  return (
    <Flex gap={1} alignItems="center">
      <Flex flexGrow={1} gap={1}>
        <WalletsDropdodown walletId={walletId} />
        <Button
          color="primary"
          onClick={handleAddToken}
        >
          <Trans>+ Add Token</Trans>
        </Button>
        <Button
          color="primary"
          variant="outlined"
          onClick={handleManageOffers}
        >
          <Trans>Manage Offers</Trans>
        </Button>
      </Flex>
      <Flex gap={1} alignItems="center">
        <Flex alignItems="center">
          <Typography variant="body1" color="textSecondary">
            <Trans>Status:</Trans>
          </Typography>
          &nbsp;
          <WalletStatus height={showDebugInformation} />
        </Flex>
        <More>
          {({ onClose }) => (
            <Box>
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
              {actions && actions({ onClose })}
            </Box>
          )}
        </More>
      </Flex>
    </Flex>
  );
}
