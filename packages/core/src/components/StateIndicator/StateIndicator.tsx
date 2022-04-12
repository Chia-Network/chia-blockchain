import React, { ReactNode } from 'react';
import styled from 'styled-components';
import Flex from '../Flex';
import State from '../../constants/State';
import StateColor from '../../constants/StateColor';
import StateIndicatorDot from './StateIndicatorDot';

const Color = {
  [State.SUCCESS]: StateColor.SUCCESS,
  [State.WARNING]: StateColor.WARNING,
  [State.ERROR]: StateColor.ERROR,
};

const StyledFlexContainer = styled(({ color: Color, ...rest }) => (
  <Flex {...rest} />
))`
  color: ${({ color }) => color};
`;

export type StateComponentProps = {
  children: ReactNode;
  state: State;
  indicator?: boolean;
  reversed?: boolean;
  color?: string;
  gap?: number;
};

export default function StateComponent(props: StateComponentProps) {
  const { children, state, indicator = false, reversed = false, color = Color[state], gap = 1 } = props;
  const iconColor = Color[state];

  return (
    <StyledFlexContainer color={color} alignItems="center" gap={gap} flexDirection={reversed ? 'row-reverse' : 'row'}>
      <span>{children}</span>
      {indicator && <StateIndicatorDot color={iconColor} />}
    </StyledFlexContainer>
  );
}
