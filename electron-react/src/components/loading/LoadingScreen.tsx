import React, { ReactNode } from 'react';
import { CircularProgress, Typography } from '@material-ui/core';
import styled from 'styled-components';
import LayoutHero from '../layout/LayoutHero';

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
    <LayoutHero>
      <StyledTypography variant="h6">
        {children}
      </StyledTypography>
      <StyledCircularProgress />
    </LayoutHero>
  );
}
