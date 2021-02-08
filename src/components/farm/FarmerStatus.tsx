import React from 'react';
import styled from 'styled-components';
import { Trans } from '@lingui/macro';
import { Flex, StateColor } from '@chia/core';
import { FiberManualRecord as FiberManualRecordIcon } from '@material-ui/icons';
import FarmerStatus from '../../constants/FarmerStatus';
import useFarmerStatus from '../../hooks/useFarmerStatus';

const Color = {
  [FarmerStatus.FARMING]: StateColor.SUCCESS,
  [FarmerStatus.SYNCHING]: StateColor.WARNING,
  [FarmerStatus.NOT_AVAILABLE]: StateColor.WARNING,
  [FarmerStatus.NOT_CONNECTED]: StateColor.ERROR,
  [FarmerStatus.NOT_RUNNING]: StateColor.ERROR,
};

const Title = {
  [FarmerStatus.FARMING]: <Trans>Farming</Trans>,
  [FarmerStatus.SYNCHING]: <Trans>Syncing</Trans>,
  [FarmerStatus.NOT_AVAILABLE]: <Trans>Not Available</Trans>,
  [FarmerStatus.NOT_CONNECTED]: <Trans>Error</Trans>,
  [FarmerStatus.NOT_RUNNING]: <Trans>Error</Trans>,
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
  const title = Title[farmerStatus];

  return (
    <StyledFlexContainer color={color} alignItems="center" gap={1}>
      <span>
        {title}
      </span>
      <StyledFiberManualRecordIcon />
    </StyledFlexContainer>
  );
}
