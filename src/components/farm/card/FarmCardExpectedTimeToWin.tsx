import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import moment from 'moment';
import { State } from '@chia/core';
import type { RootState } from '../../../modules/rootReducer';
import FarmCard from './FarmCard';
import type Plot from '../../../types/Plot';
import FullNodeState from '../../../constants/FullNodeState';
import useFullNodeState from '../../../hooks/useFullNodeState';
import FarmCardNotAvailable from './FarmCardNotAvailable';

const MINUTES_PER_BLOCK = (24 * 60) / 4608; // 0.3125

export default function FarmCardExpectedTimeToWin() {
  const fullNodeState = useFullNodeState();

  const plots = useSelector(
    (state: RootState) => state.farming_state.harvester.plots,
  );
  const totalNetworkSpace = useSelector(
    (state: RootState) => state.full_node_state.blockchain_state?.space ?? 0,
  );

  const farmerSpace = useMemo(() => {
    if (!plots) {
      return 0;
    }

    return plots.map((p: Plot) => p.file_size).reduce((a, b) => a + b, 0);
  }, [plots]);

  const proportion = totalNetworkSpace
    ? farmerSpace / totalNetworkSpace
    : 0;

  const minutes = proportion
    ? MINUTES_PER_BLOCK / proportion
    : 0;

  const expectedTimeToWin = moment.duration({ minutes }).humanize();

  if (fullNodeState !== FullNodeState.SYNCED) {
    const state = fullNodeState === FullNodeState.SYNCHING
      ? State.WARNING
      : undefined;

    return (
      <FarmCardNotAvailable
        title={
          <Trans>Estimated Time to Win</Trans>
        }
        state={state}
      />
    );
  }

  return (
    <FarmCard
      title={
        <Trans>Estimated Time to Win</Trans>
      }
      value={`${expectedTimeToWin}`}
      tooltip={
        <Trans>
          You have {(proportion * 100).toFixed(4)}% of the space on the network,
          so farming a block will take {expectedTimeToWin} in expectation.
          Actual results may take 3 to 4 times longer than this estimate.
        </Trans>
      }
    />
  );
}
