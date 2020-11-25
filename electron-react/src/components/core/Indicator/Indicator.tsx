import React, { ReactNode } from 'react';
import { Flex } from '@chia/core';
import styled from 'styled-components';

const StyledIndicator = styled.div`
  display: inline-block;
  height: 10px;
  width: 75px;
  background-color: ${({ color }) => color};
`;

type Props = {
  color: string;
  children?: ReactNode;
};

export default function PlotStatus(props: Props) {
  const { children, color } = props;

  return (
    <Flex flexDirection="column" gap={1}>
      <StyledIndicator color={color} />

      <Flex>
        {children}
      </Flex>
    </Flex>
  );
}

PlotStatus.defaultProps = {
  children: undefined,
};
