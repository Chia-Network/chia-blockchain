import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex, StateColor, StateIndicatorDot } from '@chia/core';
import {
  useGetFullNodeConnectionsQuery,
  useGetWalletConnectionsQuery,
} from '@chia/api-react';
import { ButtonGroup, Button, Popover } from '@mui/material';
import { useTheme } from '@mui/styles';
import { WalletConnections } from '@chia/wallets';
import Connections from '../fullNode/FullNodeConnections';

export default function AppStatusHeader() {
  const theme = useTheme();
  const { data: connectionsFN } = useGetFullNodeConnectionsQuery(
    {},
    { pollingInterval: 10000 },
  );
  const { data: connectionsW } = useGetWalletConnectionsQuery(
    {},
    { pollingInterval: 10000 },
  );
  const [anchorElFN, setAnchorElFN] = React.useState<HTMLButtonElement | null>(
    null,
  );
  const [anchorElW, setAnchorElW] = React.useState<HTMLButtonElement | null>(
    null,
  );

  const handleClickFN = (event: React.MouseEvent<HTMLButtonElement>) => {
    setAnchorElFN(event.currentTarget);
  };

  const handleCloseFN = () => {
    setAnchorElFN(null);
  };

  const openFN = Boolean(anchorElFN);

  const handleClickW = (event: React.MouseEvent<HTMLButtonElement>) => {
    setAnchorElW(event.currentTarget);
  };

  const handleCloseW = () => {
    setAnchorElW(null);
  };

  const openW = Boolean(anchorElW);

  const colorFN =
    connectionsFN?.length >= 1
      ? StateColor.SUCCESS
      : theme.palette.text.secondary;

  const colorW =
    connectionsW?.length >= 1
      ? StateColor.SUCCESS
      : theme.palette.text.secondary;

  return (
    <ButtonGroup variant="outlined" color="secondary" size="small">
      <Button onClick={handleClickFN}>
        <Flex gap={1} alignItems="center">
          <Flex>
            <StateIndicatorDot color={colorFN} />
          </Flex>
          <Flex>
            <Trans>Full Node</Trans>
          </Flex>
        </Flex>
      </Button>
      <Popover
        id={openFN ? 'simple-popover' : undefined}
        open={openFN}
        anchorEl={anchorElFN}
        onClose={handleCloseFN}
        anchorOrigin={{
          vertical: 'bottom',
          horizontal: 'right',
        }}
        transformOrigin={{
          horizontal: 'right',
        }}
      >
        <Connections />
      </Popover>
      <Button onClick={handleClickW}>
        <Flex gap={1} alignItems="center">
          <Flex>
            <StateIndicatorDot color={colorW} />
          </Flex>
          <Flex>
            <Trans>Wallet</Trans>
          </Flex>
        </Flex>
      </Button>
      <Popover
        id={openW ? 'simple-popover' : undefined}
        open={openW}
        anchorEl={anchorElW}
        onClose={handleCloseW}
        anchorOrigin={{
          vertical: 'bottom',
          horizontal: 'right',
        }}
        transformOrigin={{
          horizontal: 'right',
        }}
      >
        <div style={{ minWidth: '800px' }}>
          <WalletConnections walletId={1} />
        </div>
      </Popover>
    </ButtonGroup>
  );
}
