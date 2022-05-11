import React, { useMemo, useState } from 'react';
import { Trans } from '@lingui/macro';
import { DropdownActions, Flex, Form, Select } from '@chia/core';
import { Box, MenuItem, Typography, FormControl, InputLabel, Slider } from '@mui/material';
import { useForm } from 'react-hook-form';
import { WalletType } from '@chia/api';
import { orderBy } from 'lodash';
import { useGetWalletsQuery } from '@chia/api-react';

function useProfiles() {
  const { data: wallets, isLoading, error } = useGetWalletsQuery();

  const didWallets = useMemo(() => {
    if (!wallets) {
      return [];
    }
    const didWallets = wallets.filter((wallet) => wallet.type === WalletType.DISTRIBUTED_ID);
    return orderBy(didWallets, ['name'], ['asc']);
  }, [wallets]);

  return {
    isLoading,
    data: didWallets,
    error,
  };
}

export type NFTGallerySidebarProps = {
  onWalletChange: (walletId?: number) => void;
};

export default function NFTGallerySidebar(props: NFTGallerySidebarProps) {
  const { onWalletChange } = props;
  const { isLoading, data } = useProfiles();
  const [selectedWalletId, setSelectedWalletId] = useState<number | undefined>();
  const [price, setPrice] = useState([10, 50]);
  const methods = useForm({
    defaultValues: {
      status: '',
      price: '',
      tokens: '',
      collections: '',
    },
  });

  const label = useMemo(() => {
    if (isLoading) {
      return 'Loading...';
    }

    const wallet = data?.find(item => item.id === selectedWalletId);
    return wallet?.name || <Trans>All Profiles</Trans>;
  }, [data, isLoading, selectedWalletId]);


  function handleSliderChange(event: Event, newValue: number | number[]) {
    setPrice(newValue as number[]);
  }

  function handleSubmit() {}

  function handleWalletChange(newWalletId?: number) {
    setSelectedWalletId(newWalletId);
    onWalletChange(newWalletId);
  }

  return (
    <Box width="320px">
      <Box paddingY={2} paddingLeft={2} paddingRight={4}>
        <Flex flexDirection="column" gap={4}>
          <Box>
            <DropdownActions onSelect={handleWalletChange} label={label} variant="text" color="secondary" size="large" >
              {({ onClose }) => (
                <>
                  {data.map((wallet) => (
                    <MenuItem
                      key={wallet.id}
                      onClick={() => { onClose(); handleWalletChange(wallet.id); }}
                      selected={wallet.id === selectedWalletId}
                    >
                      {wallet.name}
                    </MenuItem>
                  ))}
                  <MenuItem key="all" onClick={() => { onClose(); handleWalletChange(); }} selected={selectedWalletId === undefined}>
                    <Trans>All</Trans>
                  </MenuItem>
                </>
              )}
            </DropdownActions>
            <Typography color="textSecondary">
              <Trans>Your Collectables</Trans>
            </Typography>
          </Box>


          <Form methods={methods} onSubmit={handleSubmit}>
            <Flex flexDirection="column" gap={2}>
              <FormControl color="secondary" fullWidth>
                <InputLabel>
                  <Trans>Status</Trans>
                </InputLabel>
                <Select name="status" label={<Trans>Status</Trans>}>
                  <MenuItem value="">
                    <em>
                      <Trans>All</Trans>
                    </em>
                  </MenuItem>
                </Select>
              </FormControl>

              <FormControl color="secondary" fullWidth>
                <InputLabel>
                  <Trans>Price</Trans>
                </InputLabel>
                <Select name="price" label={<Trans>Price</Trans>}>
                  <MenuItem value="">
                    <Slider
                      value={price}
                      onChange={handleSliderChange}
                      valueLabelDisplay="auto"
                      color="secondary"
                    />
                  </MenuItem>
                </Select>
              </FormControl>

              <FormControl color="secondary" fullWidth>
                <InputLabel>
                  <Trans>Tokens</Trans>
                </InputLabel>
                <Select name="tokens" label={<Trans>Tokens</Trans>}>
                  <MenuItem value="">
                    <em>
                      <Trans>All</Trans>
                    </em>
                  </MenuItem>
                </Select>
              </FormControl>

              <FormControl color="secondary" fullWidth>
                <InputLabel>
                  <Trans>Collections</Trans>
                </InputLabel>
                <Select name="collections" label={<Trans>Collections</Trans>}>
                  <MenuItem value="">
                    <em>
                      <Trans>All</Trans>
                    </em>
                  </MenuItem>
                </Select>
              </FormControl>
            </Flex>
          </Form>
        </Flex>
      </Box>
    </Box>
  );
}
