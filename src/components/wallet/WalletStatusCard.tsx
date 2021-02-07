import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import { Box, Typography } from '@material-ui/core';
import type { RootState } from '../../modules/rootReducer';

export default function WalletStatusCard(): JSX.Element {
  const syncing = useSelector(
    (state: RootState) => state.wallet_state.status.syncing,
  );
  const height = useSelector(
    (state: RootState) => state.wallet_state.status.height,
  );
  const connectionCount = useSelector(
    (state: RootState) => state.wallet_state.status.connection_count,
  );

  return (
    <div style={{ margin: 16 }}>
      <Typography variant="subtitle1">
        <Trans id="WalletStatusCard.title">Status</Trans>
      </Typography>
      <div style={{ marginLeft: 8 }}>
        <Box display="flex">
          <Box flexGrow={1}>
            <Trans id="WalletStatusCard.status">status:</Trans>
          </Box>
          <Box>
            {syncing ? (
              <Trans id="WalletStatusCard.syncing">syncing</Trans>
            ) : (
              <Trans id="WalletStatusCard.synced">synced</Trans>
            )}
          </Box>
        </Box>
        <Box display="flex">
          <Box flexGrow={1}>
            <Trans id="WalletStatusCard.height">height:</Trans>
          </Box>
          <Box>{height}</Box>
        </Box>
        <Box display="flex">
          <Box flexGrow={1}>
            <Trans id="WalletStatusCard.connections">connections:</Trans>
          </Box>
          <Box>{connectionCount}</Box>
        </Box>
      </div>
    </div>
  );
}
