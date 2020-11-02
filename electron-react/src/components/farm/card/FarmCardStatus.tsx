import React from 'react';
import styled from 'styled-components';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import { Flex } from '@chia/core';
import { FiberManualRecord as FiberManualRecordIcon } from '@material-ui/icons';
import type { RootState } from '../../../modules/rootReducer';
import FarmCard from './FarmCard';

const StyledFiberManualRecordIcon = styled(FiberManualRecordIcon)`
  font-size: 1rem;
`;

export default function FarmCardStatus() {
  const connected = useSelector(
    (state: RootState) => state.daemon_state.farmer_connected,
  );
  const running = useSelector(
    (state: RootState) => state.daemon_state.farmer_running,
  );
  const connectedNotRunning = connected && !running;
  const color = connected ? 'primary' : 'secondary';

  return (
    <FarmCard
      title={<Trans id="FarmCardStatus.title">Farming Status</Trans>}
      value={
        <Flex alignItems="center" gap={1}>
          <span>
            {running ? (
              <Trans id="FarmCardStatus.farming">Farming</Trans>
            ) : connected ? (
              <Trans id="FarmCardStatus.connected">Connected</Trans>
            ) : (
              <Trans id="FarmCardStatus.notConnected">Not Connected</Trans>
            )}
          </span>
          <StyledFiberManualRecordIcon color={color} />
        </Flex>
      }
      description={connectedNotRunning && (
        <Trans id="FarmCardStatus.connectedNotFarming">Connected but Not Farming</Trans>
      )}
      valueColor={color}
    />
  );
}
