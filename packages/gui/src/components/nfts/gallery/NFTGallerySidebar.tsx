import React from 'react';
import { Trans } from '@lingui/macro';
import { DropdownActions, Flex, Form, Select } from '@chia/core';
import { Box, MenuItem, Typography, FormControl, InputLabel } from '@mui/material';
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
  const methods = useForm({
    defaultValues: {
      status: '',
      price: '',
      tokens: '',
      collections: '',
    },
  });

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


          <Form methods={methods}>
            <Flex flexDirection="column" gap={2}>
              <FormControl color="secondary" fullWidth>
                <InputLabel>
                  <Trans>Status</Trans>
                </InputLabel>
                <Select name="status" >
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
                <Select name="price">
                  <MenuItem value="">
                    <em>
                      <Trans>All</Trans>
                    </em>
                  </MenuItem>
                </Select>
              </FormControl>

              <FormControl color="secondary" fullWidth>
                <InputLabel>
                  <Trans>Tokens</Trans>
                </InputLabel>
                <Select name="tokens">
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
                <Select name="collections">
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
