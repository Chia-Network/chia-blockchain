import React, { ReactNode } from 'react';
import { Flex } from '@chia/core';
import { LinearProgress, Typography } from '@material-ui/core';
import styled from 'styled-components';

const StyledIndicator = styled.div`
  display: inline-block;
  height: 10px;
  width: 75px;
  background-color: ${({ color }) => color};
`;

const StyledLinearProgress = styled(LinearProgress)`
  height: 10px;
  width: 75px;
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
        <Flex gap={1} alignItems="center">
          <StyledLinearProgress variant="determinate" value={progress * 100} color="secondary" />
          <Flex>
            <Typography variant="body2" color="textSecondary">
              {`${Math.round(progress * 100)}%`}
            </Typography>
          </Flex>
        </Flex>
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
