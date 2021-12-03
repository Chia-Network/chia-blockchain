import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useCurrencyCode, mojoToChiaLocaleString } from '@chia/core';
import { useGetFarmedAmountQuery } from '@chia/api-react';
import FarmCard from './FarmCard';

export default function FarmCardTotalChiaFarmed() {
  const currencyCode = useCurrencyCode();
  const { data, isLoading } = useGetFarmedAmountQuery();

  const farmedAmount = data?.farmedAmount;

  const totalChiaFarmed = useMemo(() => {
    if (farmedAmount !== undefined) {
      return (
        <>
          {mojoToChiaLocaleString(farmedAmount)}
          &nbsp;
          {currencyCode}
        </>
      );
    }
  }, [farmedAmount]);

  return (
    <FarmCard
      title={<Trans>Total Chia Farmed</Trans>}
      value={totalChiaFarmed}
      loading={isLoading}
    />
  );
}
