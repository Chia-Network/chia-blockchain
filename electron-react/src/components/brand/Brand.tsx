import React from 'react';
import styled from 'styled-components';
import { Box, BoxProps } from '@material-ui/core';
import brandSrc from './images/chia.svg';

const StyledImage = styled('img')`
  max-width: 100%;
  // animation: App-logo-spin infinite 20s linear;

  @keyframes App-logo-spin {
    from {
      transform: rotate(0deg);
    }
    to {
      transform: rotate(360deg);
    }
  }
`;

export default function Brand(props: BoxProps) {
  return (
    <Box {...props}>
      <StyledImage src={brandSrc} />
    </Box>
  );
}
