import React, { ReactNode } from 'react';
import { Flex } from '@chia/core';
import { LinearProgress } from '@material-ui/core';
import styled from 'styled-components';

const StyledIndicator = styled.div`
  display: inline-block;
  height: 10px;
  width: 75px;
  background-color: ${({ color }) => color};
`;

const StyledLinearProgress = styled(LinearProgress)`
  height: 10px;
  border-radius: 0;
`;

type Props = {
  color: string;
  children?: ReactNode;
  progress?: number;
};

export default function PlotStatus(props: Props) {
  const { children, color, progress } = props;

  return (
    <Flex flexDirection="column" gap={1}>
      {progress !== undefined ? (
        <StyledLinearProgress variant="determinate" value={progress * 100} color="secondary" />
      ) : (
        <StyledIndicator color={color} />
      )}

      <Flex>
        {children}
      </Flex>
    </Flex>
  );
}

PlotStatus.defaultProps = {
  children: undefined,
};
