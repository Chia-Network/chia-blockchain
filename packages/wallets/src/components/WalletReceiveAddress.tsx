import React from 'react';
import { Trans } from '@lingui/macro';
import {
  ButtonLoading,
  CopyToClipboard,
  Card,
  Loading,
  Flex,
  TooltipIcon,
} from '@chia/core';
import {
  useGetCurrentAddressQuery,
  useGetNextAddressMutation,
} from '@chia/api-react';
import {
  Box,
  TextField,
  InputAdornment,
  Grid,
  Typography,
} from '@mui/material';

export type WalletReceiveAddressProps = {
  walletId: number;
};

export default function WalletReceiveAddress(props: WalletReceiveAddressProps) {
  const { walletId } = props;
  const { data: address, isLoading } = useGetCurrentAddressQuery({
    walletId,
  });
  const [newAddress, { isLoading: isLoadingNewAddress }] =
    useGetNextAddressMutation();

  async function handleNewAddress() {
    await newAddress({
      walletId,
      newAddress: true,
    }).unwrap();
  }

  return (
    <Flex gap={2} flexDirection="column">
      <Flex gap={1} flexGrow={1} justifyContent="space-between">
        <Typography variant="h6">
          <Trans>Receive Address</Trans>
          &nbsp;
          <TooltipIcon>
            <Trans>
              HD or Hierarchical Deterministic keys are a type of public
              key/private key scheme where one private key can have a nearly
              infinite number of different public keys (and therefore wallet
              receive addresses) that will all ultimately come back to and be
              spendable by a single private key.
            </Trans>
          </TooltipIcon>
        </Typography>
        <ButtonLoading
          onClick={handleNewAddress}
          loading={isLoadingNewAddress}
          variant="outlined"
          data-testid="WalletReceiveAddress-new-address"
        >
          <Trans>New Address</Trans>
        </ButtonLoading>
      </Flex>

      <Card>
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
                  inputProps={{
                    'data-testid': 'WalletReceiveAddress-address',
                    readOnly: true,
                  }}
                  InputProps={{
                    endAdornment: (
                      <InputAdornment position="end">
                        <CopyToClipboard
                          value={address}
                          data-testid="WalletReceiveAddress-address-copy"
                        />
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
    </Flex>
  );
}
