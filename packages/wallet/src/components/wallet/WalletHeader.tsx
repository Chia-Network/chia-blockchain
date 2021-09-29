import React, { ReactNode } from 'react';
import { Trans } from '@lingui/macro';
import {
  More,
  Flex,
  ConfirmDialog,
} from '@chia/core';
import { useDispatch } from 'react-redux';
import {
  Box,
  Typography,
  ListItemIcon,
  MenuItem,
} from '@material-ui/core';
import {
  Delete as DeleteIcon,
} from '@material-ui/icons';
import { deleteUnconfirmedTransactions } from '../../modules/incoming';
import WalletStatus from './WalletStatus';
import useOpenDialog from '../../hooks/useOpenDialog';

type StandardWalletProps = {
  wallet_id: number;
  hideTitle?: boolean;
  title: ReactNode;
  actions?: ({ onClose } : { onClose: () => void } ) => ReactNode;
};

export default function WalletHeader(props: StandardWalletProps) {
  const { wallet_id, hideTitle, actions, title } = props;
  const dispatch = useDispatch();
  const openDialog = useOpenDialog();

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
      dispatch(deleteUnconfirmedTransactions(wallet_id));
    }
  }

  return (
    <Flex gap={1} alignItems="center">
      <Flex flexGrow={1}>
        {!hideTitle && (
          <Typography variant="h5" gutterBottom>
            {title}
          </Typography>
        )}
      </Flex>
      <Flex gap={1} alignItems="center">
        <Flex alignItems="center">
          <Typography variant="body1" color="textSecondary">
            <Trans>Wallet Status:</Trans>
          </Typography>
          &nbsp;
          <WalletStatus height />
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
