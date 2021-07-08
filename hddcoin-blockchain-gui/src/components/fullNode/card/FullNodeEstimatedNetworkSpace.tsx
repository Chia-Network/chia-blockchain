import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import FarmCard from '../../farm/card/FarmCard';
import { FormatBytes } from '@hddcoin/core';
import { RootState } from '../../../modules/rootReducer';

export default function FullNodeEstimatedNetworkSpace() {
  const state = useSelector(
    (state: RootState) => state.full_node_state.blockchain_state,
  );

  const loading = !state;
  const value = state?.space;

  return (
    <FarmCard
      loading={loading}
      valueColor="textPrimary"
      title={<Trans>Estimated Network Space</Trans>}
      tooltip={
        <Trans>
          Estimated sum of all the plotted disk space of all farmers in the
          network
        </Trans>
      }
      value={value && <FormatBytes value={value} precision={3} />}
    />
  );
}
