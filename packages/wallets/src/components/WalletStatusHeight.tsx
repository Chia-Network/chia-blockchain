import React from 'react';
import { FormatLargeNumber } from '@chia/core';
import { useGetHeightInfoQuery } from '@chia/api-react';

export default function WalletStatusHeight() {
  const { data: height, isLoading } = useGetHeightInfoQuery();
  if (isLoading) {
    return null;
  }

  if (height === undefined || height === null) {
    return null;
  }

  return (
    <>
      {'('}
      <FormatLargeNumber value={height} />
      {')'}
    </>
  );
}
