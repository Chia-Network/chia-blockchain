import React from 'react';
import styled from 'styled-components';
import { Box, BoxProps } from '@material-ui/core'
import brandSrc from "../../assets/img/chia_logo.svg";

const StyledImage = styled('img')`
  max-width: 100%;
`;

export default function Brand(props: BoxProps) {
  return (
    <Box {...props}>
      <StyledImage src={brandSrc} />
    </Box>
  );
}