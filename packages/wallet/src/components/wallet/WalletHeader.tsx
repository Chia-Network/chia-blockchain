import React, { ReactNode } from 'react';
import { Trans } from '@lingui/macro';
import {
  Back,
  More,
  Flex,
  ConfirmDialog,
} from '@chia/core';
import { useHistory } from 'react-router';
import { useDispatch } from 'react-redux';
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
import { deleteUnconfirmedTransactions } from '../../modules/incoming';
import WalletStatus from './WalletStatus';
import useOpenDialog from '../../hooks/useOpenDialog';
import WalletsDropdodown from './WalletsDropdown';

type StandardWalletProps = {
  walletId: number;
  actions?: ({ onClose } : { onClose: () => void } ) => ReactNode;
};

export default function WalletHeader(props: StandardWalletProps) {
  const { walletId, actions } = props;
  const dispatch = useDispatch();
  const openDialog = useOpenDialog();
  const history = useHistory();

  async function handleDeleteUnconfirmedTransactions() {
    const deleteConfirmed = await openDialog(
      <ConfirmDialog
        title={<Trans>Confirmation</Trans>}
        confirmTitle={<Trans>Delete</Trans>}
        confirmColor="danger"
      >
        <Trans>Are you sure you want to delete unconfirmed transactions?</Trans>
      </ConfirmDialog>,
    );

    // @ts-ignore
    if (deleteConfirmed) {
      dispatch(deleteUnconfirmedTransactions(walletId));
    }
  }

  function handleAddToken() {
    history.push('/dashboard/wallets/create/simple');
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
      </Flex>
      <Flex gap={1} alignItems="center">
        <Flex alignItems="center">
          <Typography variant="body1" color="textSecondary">
            <Trans>Status:</Trans>
          </Typography>
          &nbsp;
          <WalletStatus />
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
