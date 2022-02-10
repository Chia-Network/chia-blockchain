import React from 'react';
import { Trans } from '@lingui/macro';
import { FormatBytes, CardSimple } from '@chia/core';
import { useGetBlockchainStateQuery } from '@chia/api-react';

export default function FarmCardTotalNetworkSpace() {
  const { data, isLoading, error } = useGetBlockchainStateQuery();
  const totalNetworkSpace = data?.space ?? 0;

  return (
    <CardSimple
      title={<Trans>Total Network Space</Trans>}
      value={<FormatBytes value={totalNetworkSpace} precision={3} />}
      description={<Trans>Best estimate over last 24 hours</Trans>}
      loading={isLoading}
      error={error}
    />
  );
}
