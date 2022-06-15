import React, { useState } from 'react';
import { t, Trans } from '@lingui/macro';
import { CopyToClipboard, Loading, Flex } from '@chia/core';
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

export default function WalletReceiveAddressField(props: WalletReceiveAddressProps) {
  const { walletId = 1, ...rest } = props;
  const { data: address = '' } = useGetCurrentAddressQuery({
    walletId,
  });
  const [newAddress] = useGetNextAddressMutation();
  const [isLoading, setIsLoading] = useState<boolean>(false);

  async function handleNewAddress() {
    try {
      setIsLoading(true);
      await newAddress({
        walletId,
        newAddress: true,
      }).unwrap();
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <TextField
      label={<Trans>Receive Address</Trans>}
      value={address}
      placeholder={t`Loading...`}
      variant="filled"
      InputProps={{
        readOnly: true,
        startAdornment: (
          <InputAdornment position="start">
            <Flex justifyContent="center" minWidth={35}>
              {isLoading ? (
                <Loading size="1em" />
              ) : (
                <IconButton onClick={handleNewAddress} size="small">
                  <Autorenew />
                </IconButton>
            )}
            </Flex>
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
