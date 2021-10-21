import React from 'react';
import { FormatLargeNumber } from '@chia/core';
import { useGetSyncStatusQuery } from '@chia/api-react';

export default function WalletStatusHeight() {
  const { data: walletState, isLoading } = useGetSyncStatusQuery();
  if (isLoading || !walletState) {
    return null;
  }

  const currentHeight = walletState?.height;
  if (currentHeight === undefined || currentHeight === null) {
    return null;
  }

  return (
    <>
      {'('}
      <FormatLargeNumber value={currentHeight} />
      {')'}
    </>
  );
}
