import React from 'react';
import { Trans } from '@lingui/macro';
import { FormatBytes, CardSimple } from '@chia/core';
import { useGetBlockchainStateQuery } from '@chia/api-react';

export default function FullNodeEstimatedNetworkSpace() {
  const { data, isLoading, error } = useGetBlockchainStateQuery();
  const value = data?.space;

  return (
    <CardSimple
      loading={isLoading}
      valueColor="textPrimary"
      title={<Trans>Estimated Network Space</Trans>}
      tooltip={
        <Trans>
          Estimated sum of all the plotted disk space of all farmers in the
          network
        </Trans>
      }
      value={value && <FormatBytes value={value} precision={3} />}
      error={error}
    />
  );
}
