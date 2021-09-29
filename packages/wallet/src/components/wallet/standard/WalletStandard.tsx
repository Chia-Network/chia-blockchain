import React /* , { ReactNode } */ from 'react';
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
  // ExpandMore as ExpandMoreIcon,
  // Help as HelpIcon,
  Delete as DeleteIcon,
} from '@material-ui/icons';
import WalletHistory from '../WalletHistory';
// import useCurrencyCode from '../../../hooks/useCurrencyCode';
import { deleteUnconfirmedTransactions } from '../../../modules/incoming';
// import WalletGraph from '../WalletGraph';
import WalletCards from './WalletCards';
import WalletStatus from '../WalletStatus';
import useOpenDialog from '../../../hooks/useOpenDialog';
import WalletReceiveAddress from '../WalletReceiveAddress';
import WalletSend from '../WalletSend';
import WalletHeader from '../WalletHeader';

type StandardWalletProps = {
  wallet_id: number;
  showTitle?: boolean;
};

export default function StandardWallet(props: StandardWalletProps) {
  const { wallet_id, showTitle } = props;
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
    <Flex flexDirection="column" gap={1}>
      <WalletHeader
        wallet_id={wallet_id}
        title={<Trans>Chia Wallet</Trans>}
      />

      <Flex flexDirection="column" gap={3}>
        <WalletCards wallet_id={wallet_id} />
        <WalletReceiveAddress walletId={wallet_id} />
        <WalletSend wallet_id={wallet_id} />
        <WalletHistory walletId={wallet_id} />
      </Flex>
    </Flex>
  );
}
