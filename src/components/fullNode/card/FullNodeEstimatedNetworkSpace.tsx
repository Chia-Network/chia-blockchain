import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import FarmCard from '../../farm/card/FarmCard';
import { FormatBytes } from '@chia/core';

export default function FullNodeEstimatedNetworkSpace() {
  const value = useSelector(
    (state) => state.full_node_state.blockchain_state.space,
  );

  return (
    <FarmCard
      valueColor="textPrimary"
      title={<Trans>Estimated Network Space</Trans>}
      tooltip={
        <Trans>
          Estimated sum of all the plotted disk space of all farmers in the
          network
        </Trans>
      }
      value={<FormatBytes value={value} precision={3} />}
    />
  );
}
