import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useCurrencyCode } from '@chia/core';
import { useGetFarmedAmountQuery } from '@chia/api-react';
import FarmCard from './FarmCard';
import { mojo_to_chia } from '../../../util/chia';

export default function FarmCardBlockRewards() {
  const currencyCode = useCurrencyCode();
  const { data, isLoading } = useGetFarmedAmountQuery();

  const farmerRewardAmount = data?.farmerRewardAmount;
  const poolRewardAmount = data?.poolRewardAmount;

  const blockRewards = useMemo(() => {
    if (farmerRewardAmount !== undefined && poolRewardAmount !== undefined) {
      const val =
        BigInt(farmerRewardAmount.toString()) +
        BigInt(poolRewardAmount.toString());
      return mojo_to_chia(val);
    }
  }, [farmerRewardAmount, poolRewardAmount]);

  return (
    <FarmCard
      title={<Trans>{currencyCode} Block Rewards</Trans>}
      description={<Trans>Without fees</Trans>}
      value={blockRewards}
      loading={isLoading}
    />
  );
}
