import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import { Flex, Form, Select } from '@chia/core';
import { Box, MenuItem, FormControl, InputLabel, Slider } from '@mui/material';
import { useForm } from 'react-hook-form';
import NFTProfileDropdown from '../NFTProfileDropdown';

export type NFTGallerySidebarProps = {
  onWalletChange: (walletId?: number) => void;
};

export default function NFTGallerySidebar(props: NFTGallerySidebarProps) {
  const { onWalletChange } = props;
  const [price, setPrice] = useState([10, 50]);
  const methods = useForm({
    defaultValues: {
      status: '',
      price: '',
      tokens: '',
      collections: '',
    },
  });

  function handleSliderChange(event: Event, newValue: number | number[]) {
    setPrice(newValue as number[]);
  }

  function handleSubmit() {}

  return (
    <Box width="320px">
      <Box paddingY={2} paddingLeft={2} paddingRight={4}>
        <Flex flexDirection="column" gap={4}>
          <NFTProfileDropdown onChange={onWalletChange} />
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
