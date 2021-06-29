import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import FarmCard from "../../farm/card/FarmCard";
import { FormatLargeNumber } from '@chia/core';

export default function FullNodeCardTotalIterations() {
  const value = useSelector(
    (state) => state.full_node_state.blockchain_state.peak?.total_iters ?? 0
  );

  return (
    <FarmCard
      valueColor="textPrimary"
      title={<Trans>Total Iterations</Trans>}
      tooltip={<Trans>Total iterations since the start of the blockchain</Trans>}
      value={<FormatLargeNumber value={value} />}
    />
  );
}