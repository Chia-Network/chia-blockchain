import React from 'react';
import { Trans } from '@lingui/macro';
import { CardSimple } from '@chia/core';
import { ServiceName } from '@chia/api';
import { useIsServiceRunningQuery } from '@chia/api-react';

export default function FullNodeCardConnectionStatus() {
  const { data: isRunning, isLoading, error } = useIsServiceRunningQuery({
    service: ServiceName.FULL_NODE,
  }, {
    pollingInterval: 1000,
  });

  return (
    <CardSimple
      loading={isLoading}
      valueColor={isRunning ? 'primary' : 'textPrimary'}
      title={<Trans>Connection Status</Trans>}
      value={
        isRunning ? <Trans>Connected</Trans> : <Trans>Not connected</Trans>
      }
      error={error}
    />
  );
}
