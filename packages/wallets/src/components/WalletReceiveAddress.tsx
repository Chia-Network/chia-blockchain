import React from 'react';
import { Trans } from '@lingui/macro';
import { Button, CopyToClipboard, Card, Loading } from '@chia/core';
import { useGetCurrentAddressQuery, useGetNextAddressMutation } from '@chia/api-react';
import {
  Box,
  TextField,
  InputAdornment,
  Grid,
} from '@mui/material';

type WalletReceiveAddressProps = {
  walletId: number;
};

export default function WalletReceiveAddress(props: WalletReceiveAddressProps) {
  const { walletId } = props;
  const { data: address, isLoading } = useGetCurrentAddressQuery({
    walletId,
  });
  const [newAddress] = useGetNextAddressMutation();

  async function handleNewAddress() {
    await newAddress({
      walletId,
      newAddress: true,
    }).unwrap();
  }

  return (
    <Card
      title={<Trans>Receive Address</Trans>}
      action={
        <Button onClick={handleNewAddress} variant="outlined">
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
            {isLoading ? (
              <Loading center />
            ) : (
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
            )}
          </Box>
        </Box>
      </Grid>
    </Card>
  );
}
