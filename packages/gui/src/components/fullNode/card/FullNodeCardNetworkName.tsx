import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import FarmCard from '../../farm/card/FarmCard';
import type { RootState } from '../../../modules/rootReducer';

export default function FullNodeCardNetworkName() {
  const networkInfo = useSelector(
    (state: RootState) => state.wallet_state.network_info,
  );

  const loading = !networkInfo;
  const networkName = networkInfo?.network_name;

  return (
    <FarmCard
      loading={loading}
      valueColor="textPrimary"
      title={<Trans>Network Name</Trans>}
      value={networkName}
    />
  );
}
