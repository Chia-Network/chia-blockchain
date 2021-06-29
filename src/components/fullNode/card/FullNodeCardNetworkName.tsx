import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import FarmCard from "../../farm/card/FarmCard";

export default function FullNodeCardNetworkName() {
  const networkInfo = useSelector(
    (state) => state.wallet_state.network_info,
  );
  
  const networkName = networkInfo?.network_name;

  return (
    <FarmCard
      valueColor="textPrimary"
      title={
        <Trans>Network Name</Trans>
      }
      value={networkName}
    />
  );
}