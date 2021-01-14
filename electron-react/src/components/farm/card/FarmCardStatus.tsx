import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import { StateIndicator, State } from '@chia/core';
import type { RootState } from '../../../modules/rootReducer';
import FarmCard from './FarmCard';
import useFullNodeState from '../../../hooks/useFullNodeState';
import FullNodeState from '../../../constants/FullNodeState';
import FarmCardNotAvailable from './FarmCardNotAvailable';

export default function FarmCardStatus() {
  const fullNodeState = useFullNodeState();
  const farmerConnected = useSelector(
    (state: RootState) => state.daemon_state.farmer_connected,
  );
  const farmerRunning = useSelector(
    (state: RootState) => state.daemon_state.farmer_running,
  );

  if (fullNodeState === FullNodeState.SYNCHING) {
    return (
      <FarmCard
        title={<Trans id="FarmCardStatus.title">Farming Status</Trans>}
        value={(
          <StateIndicator state={State.WARNING} indicator>
            <Trans id="FarmCardStatus.synching">Syncing</Trans>
          </StateIndicator>
        )}
      />
    );
  }

  if (fullNodeState === FullNodeState.ERROR) {
    return (
      <FarmCardNotAvailable
        title={
          <Trans id="FarmCardStatus.title">Farming Status</Trans>
        }
      />
    );
  }

  if (!farmerConnected) {
    return (
      <FarmCard
        title={<Trans id="FarmCardStatus.title">Farming Status</Trans>}
        value={(
          <StateIndicator state={State.ERROR} indicator>
            <Trans id="FarmCardStatus.error">Error</Trans>
          </StateIndicator>
        )}
        description={<Trans id="FarmCardStatus.farmerIsNotConnected">Farmer is not connected</Trans>}
      />
    );
  }

  if (!farmerRunning) {
    return (
      <FarmCard
        title={<Trans id="FarmCardStatus.title">Farming Status</Trans>}
        value={(
          <StateIndicator state={State.ERROR} indicator>
            <Trans id="FarmCardStatus.error">Error</Trans>
          </StateIndicator>
        )}
        description={<Trans id="FarmCardStatus.farmerIsNotRunning">Farmer is not running</Trans>}
      />
    );
  }

  return (
    <FarmCard
      title={<Trans id="FarmCardStatus.title">Farming Status</Trans>}
      value={(
        <StateIndicator state={State.SUCCESS} indicator>
          <Trans id="FarmerStatus.farming">Farming</Trans>
        </StateIndicator>
      )}
    />
  );
}
