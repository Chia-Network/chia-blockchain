import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import BigNumber from 'bignumber.js';
import {
  useGetBlockchainStateQuery,
  useGetTotalHarvestersSummaryQuery,
} from '@chia/api-react';
import moment from 'moment';
import { State, CardSimple } from '@chia/core';
import FullNodeState from '../../../constants/FullNodeState';
import useFullNodeState from '../../../hooks/useFullNodeState';
import FarmCardNotAvailable from './FarmCardNotAvailable';

const MINUTES_PER_BLOCK = (24 * 60) / 4608; // 0.3125

export default function FarmCardExpectedTimeToWin() {
  const { state: fullNodeState } = useFullNodeState();

  const {
    data,
    isLoading: isLoadingBlockchainState,
    error: errorBlockchainState,
  } = useGetBlockchainStateQuery();
  const {
    totalPlotSize,
    isLoading: isLoadingTotalHarvesterSummary,
    error: errorLoadingPlots,
  } = useGetTotalHarvestersSummaryQuery();

  const isLoading = isLoadingBlockchainState || isLoadingTotalHarvesterSummary;
  const error = errorBlockchainState || errorLoadingPlots;

  const totalNetworkSpace = useMemo(
    () => new BigNumber(data?.space ?? 0),
    [data],
  );

  const proportion = useMemo(() => {
    if (isLoading || totalNetworkSpace.isZero()) {
      return new BigNumber(0);
    }

    return totalPlotSize.div(totalNetworkSpace);
  }, [isLoading, totalPlotSize, totalNetworkSpace]);

  const minutes = !proportion.isZero()
    ? new BigNumber(MINUTES_PER_BLOCK).div(proportion)
    : new BigNumber(0);

  const expectedTimeToWin = moment
    .duration({
      minutes: minutes.toNumber(),
    })
    .humanize();

  if (fullNodeState !== FullNodeState.SYNCED) {
    const state =
      fullNodeState === FullNodeState.SYNCHING ? State.WARNING : undefined;

    return (
      <FarmCardNotAvailable
        title={<Trans>Estimated Time to Win</Trans>}
        state={state}
      />
    );
  }

  return (
    <CardSimple
      title={<Trans>Estimated Time to Win</Trans>}
      value={`${expectedTimeToWin}`}
      tooltip={
        <Trans>
          You have {(proportion * 100).toFixed(4)}% of the space on the network,
          so farming a block will take {expectedTimeToWin} in expectation.
          Actual results may take 3 to 4 times longer than this estimate.
        </Trans>
      }
      loading={isLoading}
      error={error}
    />
  );
}
