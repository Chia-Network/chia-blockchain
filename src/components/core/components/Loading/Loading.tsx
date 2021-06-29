import React, { ReactNode } from 'react';
import {
  CircularProgress,
  CircularProgressProps,
  Typography,
} from '@material-ui/core';
import styled from 'styled-components';
import Flex from '../Flex';

const StyledCircularProgress = styled(CircularProgress)`
  color: ${({ theme }) =>
    theme.palette.type === 'dark' ? 'white' : 'inherit'}; ;
`;

type Props = CircularProgressProps & {
  children?: ReactNode;
};

export default function Loading(props: Props) {
  const { children, center, ...rest } = props;

  if (children) {
    return (
      <Flex flexDirection="column" gap={1} alignItems="center">
        <StyledCircularProgress {...rest} />
        <Typography variant="body1" align="center">
          {children}
        </Typography>
      </Flex>
    );
  }

  return <StyledCircularProgress {...rest} />;
}
