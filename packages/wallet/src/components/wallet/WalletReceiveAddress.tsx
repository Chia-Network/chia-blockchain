import React from 'react';
import { Trans } from '@lingui/macro';
import { CopyToClipboard, Card } from '@chia/core';
import { useDispatch } from 'react-redux';
import {
  Box,
  Button,
  TextField,
  InputAdornment,
  Grid,
} from '@material-ui/core';
import { get_address } from '../../modules/message';
import useWallet from '../../hooks/useWallet';

type WalletReceiveAddressProps = {
  walletId: number;
};

export default function WalletReceiveAddress(props: WalletReceiveAddressProps) {
  const { walletId } = props;

  const dispatch = useDispatch();
  const { wallet, loading } = useWallet(walletId);
  if (!wallet || loading) {
    return null;
  }

  const { address } = wallet;

  function newAddress() {
    dispatch(get_address(walletId, true));
  }

  return (
    <Card
      title={<Trans>Receive Address</Trans>}
      action={
        <Button onClick={newAddress} variant="outlined">
          <Trans>New Address</Trans>
        </Button>
      }
      tooltip={
        <Trans>
          HD or Hierarchical Deterministic keys are a type of public key/private
          key scheme where one private key can have a nearly infinite number of
          different public keys (and therefor wallet receive addresses) that
          will all ultimately come back to and be spendable by a single private
          key.
        </Trans>
      }
    >
      <Grid item xs={12}>
        <Box display="flex">
          <Box flexGrow={1}>
            <TextField
              label={<Trans>Address</Trans>}
              value={address}
              variant="filled"
              InputProps={{
                readOnly: true,
                endAdornment: (
                  <InputAdornment position="end">
                    <CopyToClipboard value={address} />
                  </InputAdornment>
                ),
              }}
              fullWidth
            />
          </Box>
        </Box>
      </Grid>
    </Card>
  );
}