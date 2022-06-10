import React from 'react';
import { Trans } from '@lingui/macro';
import { CopyToClipboard } from '@chia/core';
import { useGetCurrentAddressQuery, useGetNextAddressMutation } from '@chia/api-react';
import {
  TextField,
  InputAdornment,
  IconButton,
} from '@mui/material';
import { Autorenew } from '@mui/icons-material';

export type WalletReceiveAddressProps = {
  walletId?: number;
};

export default function WalletReceiveAddress(props: WalletReceiveAddressProps) {
  const { walletId = 1, ...rest } = props;
  const { data: address = '' } = useGetCurrentAddressQuery({
    walletId,
  });
  const [newAddress] = useGetNextAddressMutation();

  const finallAddress = address;

  async function handleNewAddress() {
    await newAddress({
      walletId,
      newAddress: true,
    }).unwrap();
  }

  return (
    <TextField
      label={<Trans>Receive Address</Trans>}
      value={finallAddress}
      placeholder="Loading..."
      variant="filled"
      InputProps={{
        readOnly: true,
        startAdornment: (
          <InputAdornment position="start">
            <IconButton onClick={handleNewAddress} size="small">
              <Autorenew />
            </IconButton>
          </InputAdornment>
        ),
        endAdornment: (
          <InputAdornment position="end">
            <CopyToClipboard value={address} />
          </InputAdornment>
        ),
      }}
      {...rest}
    />
  );
}
