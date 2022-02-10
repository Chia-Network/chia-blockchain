import React from 'react';
import { Trans } from '@lingui/macro';
import { StateIndicator, State, CardSimple } from '@chia/core';
import FarmCardNotAvailable from './FarmCardNotAvailable';
import useFarmerStatus from '../../../hooks/useFarmerStatus';
import FarmerStatus from '../../../constants/FarmerStatus';

export default function FarmCardStatus() {
  const farmerStatus = useFarmerStatus();

  if (farmerStatus === FarmerStatus.SYNCHING) {
    return (
      <CardSimple
        title={<Trans>Farming Status</Trans>}
        value={
          <StateIndicator state={State.WARNING} indicator>
            <Trans>Syncing</Trans>
          </StateIndicator>
        }
      />
    );
  }

  if (farmerStatus === FarmerStatus.NOT_AVAILABLE) {
    return <FarmCardNotAvailable title={<Trans>Farming Status</Trans>} />;
  }

  if (farmerStatus === FarmerStatus.NOT_CONNECTED) {
    return (
      <CardSimple
        title={<Trans>Farming Status</Trans>}
        value={
          <StateIndicator state={State.ERROR} indicator>
            <Trans>Error</Trans>
          </StateIndicator>
        }
        description={<Trans>Farmer is not connected</Trans>}
      />
    );
  }

  if (farmerStatus === FarmerStatus.NOT_RUNNING) {
    return (
      <CardSimple
        title={<Trans>Farming Status</Trans>}
        value={
          <StateIndicator state={State.ERROR} indicator>
            <Trans>Error</Trans>
          </StateIndicator>
        }
        description={<Trans>Farmer is not running</Trans>}
      />
    );
  }

  return (
    <CardSimple
      title={<Trans>Farming Status</Trans>}
      value={
        <StateIndicator state={State.SUCCESS} indicator>
          <Trans>Farming</Trans>
        </StateIndicator>
      }
    />
  );
}
