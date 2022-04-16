import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex, StateColor, StateIndicatorDot } from '@chia/core';
import { useGetWalletConnectionsQuery } from '@chia/api-react';
import { Box, ButtonGroup, Button } from '@mui/material';
import WalletStatus from './WalletStatus';
import { useTheme } from '@mui/styles';

export default function WalletStatusHeader() {
  const theme = useTheme();
  const { data: connections } = useGetWalletConnectionsQuery();

  const color = connections?.length >= 1
    ? StateColor.SUCCESS
    : theme.palette.text.secondary;

  return (
    <ButtonGroup variant="outlined" color="secondary" size="small">
      <Button>
        <WalletStatus color={theme.palette.text.primary} indicator reversed justChildren />
      </Button>
      <Button>
        <Flex gap={1} alignItems="center">
          <StateIndicatorDot color={color} />
          <Box>
            {connections?.length > 0 ? (
              <Trans>Connected ({connections?.length})</Trans>
            ) : (
              <Trans>Not Connected</Trans>
            )}
          </Box>
        </Flex>
      </Button>
    </ButtonGroup>
  );
}
