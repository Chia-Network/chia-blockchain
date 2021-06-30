import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import FarmCard from '../../farm/card/FarmCard';
import { unix_to_short_date } from '../../../util/utils';
import type { RootState } from '../../../modules/rootReducer';

export default function FullNodeCardPeakTime() {
  const latestPeakTimestamp = useSelector(
    (state: RootState) => state.full_node_state?.latest_peak_timestamp,
  );

  const value = latestPeakTimestamp
    ? unix_to_short_date(latestPeakTimestamp)
    : '';
  
  const loading = value === undefined;

  return (
    <FarmCard
      loading={loading}
      valueColor="textPrimary"
      title={<Trans>Peak Time</Trans>}
      tooltip={<Trans>This is the time of the latest peak sub block.</Trans>}
      value={value}
    />
  );
}
