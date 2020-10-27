import React from 'react';
import styled from 'styled-components';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import { FiberManualRecord as FiberManualRecordIcon } from '@material-ui/icons';
import type { RootState } from '../../../modules/rootReducer';
import FarmCard from './FarmCard';
import Flex from '../../flex/Flex';

const StyledFiberManualRecordIcon = styled(FiberManualRecordIcon)`
  font-size: 1rem;
`;

export default function FarmCardStatus() {
  const connected = useSelector((state: RootState) => state.daemon_state.farmer_connected);
  const color = connected ? 'primary' : 'secondary';

  return (
    <FarmCard
      title={<Trans id="FarmCardStatus.title">Farming Status</Trans>}
      value={(
        <Flex alignItems="center" gap={1}>
          <span>
            {connected
              ? <Trans id="FarmCardStatus.farming">Farming</Trans>
              : <Trans id="FarmCardStatus.notConnected">Not connected</Trans>
            }
          </span>
          <StyledFiberManualRecordIcon color={color} />
        </Flex>
      )}
      valueColor={color}
    />
  );
}
