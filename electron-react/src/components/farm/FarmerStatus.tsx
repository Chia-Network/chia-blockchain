import React from 'react';
import styled from 'styled-components';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import { Flex } from '@chia/core';
import { FiberManualRecord as FiberManualRecordIcon } from '@material-ui/icons';
import type { RootState } from '../../modules/rootReducer';
import FarmerStatus from '../../constants/FarmerStatus';
import StateColor from '../../constants/StateColor';


const Color = {
  [FarmerStatus.FARMING]: StateColor.SUCCESS,
  [FarmerStatus.SYNCHING]: StateColor.WARNING,
  [FarmerStatus.ERROR]: StateColor.ERROR,
};

const StyledFiberManualRecordIcon = styled(FiberManualRecordIcon)`
  font-size: 1rem;
`;

const StyledFlexContainer = styled(({ color: Color, ...rest }) => <Flex {...rest} />)`
  color: ${({ color }) => color};
`;

function getFarmerStatus(connected: boolean, running: boolean, blockchainSynching: boolean): FarmerStatus {
  if (blockchainSynching) {
    return FarmerStatus.SYNCHING;
  } else if (connected && running) {
    return FarmerStatus.FARMING;
  }

  return FarmerStatus.ERROR;
}

export default function FarmerStatusComponent() {
  const blockchainSynching = useSelector(
    (state: RootState) => !!state.full_node_state.blockchain_state?.sync?.sync_mode,
  );
  const connected = useSelector(
    (state: RootState) => state.daemon_state.farmer_connected,
  );
  const running = useSelector(
    (state: RootState) => state.daemon_state.farmer_running,
  );

  const farmerStatus = getFarmerStatus(connected, running, blockchainSynching);
  const color = Color[farmerStatus];

  return (
    <StyledFlexContainer color={color} alignItems="center" gap={1}>
      <span>
        {farmerStatus === FarmerStatus.FARMING ? (
          <Trans id="FarmerStatus.farming">Farming</Trans>
        ) : farmerStatus === FarmerStatus.SYNCHING ? (
          <Trans id="FarmerStatus.synching">Synching</Trans>
        ) : (
          <Trans id="FarmerStatus.error">Error</Trans>
        )}
      </span>
      <StyledFiberManualRecordIcon />
    </StyledFlexContainer>
  );
}
