import React from 'react';
import styled from 'styled-components';
import { Trans } from '@lingui/macro';
import { Flex } from '@chia/core';
import { FiberManualRecord as FiberManualRecordIcon } from '@material-ui/icons';
import FarmerStatus from '../../constants/FarmerStatus';
import StateColor from '../../constants/StateColor';
import useFarmerStatus from '../../hooks/useFarmerStatus';

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

export default function FarmerStatusComponent() {
  const farmerStatus = useFarmerStatus();
  const color = Color[farmerStatus];

  return (
    <StyledFlexContainer color={color} alignItems="center" gap={1}>
      <span>
        {farmerStatus === FarmerStatus.FARMING ? (
          <Trans id="FarmerStatus.farming">Farming</Trans>
        ) : farmerStatus === FarmerStatus.SYNCHING ? (
          <Trans id="FarmerStatus.synching">Syncing</Trans>
        ) : (
          <Trans id="FarmerStatus.error">Error</Trans>
        )}
      </span>
      <StyledFiberManualRecordIcon />
    </StyledFlexContainer>
  );
}
