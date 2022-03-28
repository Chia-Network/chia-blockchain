import React from 'react';
import styled from 'styled-components';
import { Box, BoxProps } from '@mui/material';
import { Chia } from '@chia/icons';

const StyledChia = styled(Chia)`
  max-width: 100%;
  width: auto;
  height: auto;
`;

export default function Logo(props: BoxProps) {
  return (
    <Box {...props}>
      <StyledChia />
    </Box>
  );
}
