import React, { ReactNode } from 'react';
import { CircularProgress, Typography, Box } from '@material-ui/core';
import styled from 'styled-components';

const StyledWrapper = styled(Box)`
  height: 100%;
  background: linear-gradient(45deg, #222222 30%, #333333 90%);
  font-family: 'Open Sans, sans-serif';
`;

const StyledCircularProgress = styled(CircularProgress)`
  color: white;
`;

const StyledTypography = styled(Typography)`
  color: white;
`;

type Props = {
  children: ReactNode,
};

export default function LoadingScreen(props: Props) {
  const { children } = props;

  return (
    <StyledWrapper
      display="flex"
      flexDirection="column"
      justifyContent="center"
      alignItems="center"
    >
      <StyledTypography variant="h6">
        {children}
      </StyledTypography>
      <StyledCircularProgress />
    </StyledWrapper>
  );
}
