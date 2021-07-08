import React from 'react';
import styled from 'styled-components';
import { Box, BoxProps } from '@material-ui/core';
import { HDDcoin } from '@hddcoin/icons';

const StyledHDDcoin = styled(HDDcoin)`
  max-width: 100%;
  width: auto;
  height: auto;
`;

export default function Logo(props: BoxProps) {
  return (
    <Box {...props}>
      <StyledHDDcoin />
    </Box>
  );
}
