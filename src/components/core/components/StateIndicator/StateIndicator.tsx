import React, { ReactNode } from 'react';
import styled from 'styled-components';
import { FiberManualRecord as FiberManualRecordIcon } from '@material-ui/icons';
import Flex from '../Flex';
import State from '../../constants/State';
import StateColor from '../../constants/StateColor';

const Color = {
  [State.SUCCESS]: StateColor.SUCCESS,
  [State.WARNING]: StateColor.WARNING,
  [State.ERROR]: StateColor.ERROR,
};

const StyledFiberManualRecordIcon = styled(FiberManualRecordIcon)`
  font-size: 1rem;
`;

const StyledFlexContainer = styled(({ color: Color, ...rest }) => (
  <Flex {...rest} />
))`
  color: ${({ color }) => color};
`;

type Props = {
  children: ReactNode;
  state: State;
  indicator?: boolean;
};

export default function StateComponent(props: Props) {
  const { children, state, indicator } = props;
  const color = Color[state];

  return (
    <StyledFlexContainer color={color} alignItems="center" gap={1}>
      <span>{children}</span>
      {indicator && <StyledFiberManualRecordIcon />}
    </StyledFlexContainer>
  );
}
