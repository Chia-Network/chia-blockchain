import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import moment from 'moment';
import type { RootState } from '../../../modules/rootReducer';
import FarmCard from './FarmCard';
import type Plot from '../../../types/Plot';

export default function FarmCardExpectedTimeToWin() {
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

  const proportion = totalNetworkSpace ? farmerSpace / totalNetworkSpace : 0;

  const minutes = proportion ? 5 / proportion : 0;

  const totalHours = moment.duration({ minutes }).humanize();

  return (
    <FarmCard
      title={
        <Trans id="FarmCardExpectedTimeToWin.title">Expected Time to Win</Trans>
      }
      value={`${totalHours}`}
      tooltip={
        <Trans id="FarmCardExpectedTimeToWin.tooltip">
          You have {(proportion * 100).toFixed(4)}% of the space on the network,
          so farming a block will take {totalHours} in expectation.
        </Trans>
      }
    />
  );
}
