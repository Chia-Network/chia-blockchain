import React from 'react';
import { Trans } from '@lingui/macro';
import { CardSimple } from '@chia/core';
import { ServiceName } from '@chia/api';
import { useService } from '@chia/api-react';

export default function FullNodeCardConnectionStatus() {
  const { isRunning, isLoading, error } = useService(ServiceName.FULL_NODE);

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
