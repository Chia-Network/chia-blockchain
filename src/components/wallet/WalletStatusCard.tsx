import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import { Box, Typography } from '@material-ui/core';
import type { RootState } from '../../modules/rootReducer';

export default function WalletStatusCard() {
  const syncing = useSelector(
    (state: RootState) => state.wallet_state.status.syncing,
  );
  const genesis_initialized = useSelector(
    (state: RootState) => state.wallet_state.status.genesis_initialized,
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
        <Trans>Status</Trans>
      </Typography>
      <div style={{ marginLeft: 8 }}>
        <Box display="flex">
          <Box flexGrow={1}>
            <Trans>status:</Trans>
          </Box>
          <Box>
            {genesis_initialized ? (
              syncing ? (
                <Trans>syncing</Trans>
              ) : (
                <Trans>synced</Trans>
              )
            ) : (
              <Trans>Waiting for network to launch</Trans>
            )}
          </Box>
        </Box>
        <Box display="flex">
          <Box flexGrow={1}>
            <Trans>height:</Trans>
          </Box>
          <Box>{height}</Box>
        </Box>
        <Box display="flex">
          <Box flexGrow={1}>
            <Trans>connections:</Trans>
          </Box>
          <Box>{connectionCount}</Box>
        </Box>
      </div>
    </div>
  );
}
