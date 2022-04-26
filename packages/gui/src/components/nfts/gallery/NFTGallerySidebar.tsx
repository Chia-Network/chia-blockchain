import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import { DropdownActions, Flex, Form, Select } from '@chia/core';
import { Box, MenuItem, Typography, FormControl, InputLabel, Slider } from '@mui/material';
import { useForm } from 'react-hook-form';

function useProfiles() {
  return {
    isLoading: false,
    data: [{
      id: 3,
      name: 'John Doe Mocked',
    }, {
      id: 4,
      name: 'Adam Mocked',
    }],
  };
}

export default function NFTGallerySidebar() {
  const { isLoading, data } = useProfiles();
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
          <Box>
            <DropdownActions label={<Trans>All Profiles</Trans>} variant="text" color="secondary" size="large" >
              {({ onClose }) => data.map((profile) => (
                <MenuItem key={profile.id} onClick={onClose}>
                  {profile.name}
                </MenuItem>
              ))}
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
