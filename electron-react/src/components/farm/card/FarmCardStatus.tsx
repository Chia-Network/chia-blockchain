import React from 'react';
import { Trans } from '@lingui/macro';
import FarmCard from './FarmCard';
import FarmStatus from '../FarmerStatus';

export default function FarmCardStatus() {
  return (
    <FarmCard
      title={<Trans id="FarmCardStatus.title">Farming Status</Trans>}
      value={<FarmStatus />}
    />
  );
}
