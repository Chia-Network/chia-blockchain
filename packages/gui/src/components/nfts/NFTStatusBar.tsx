import React from 'react';
import { Flex } from '@chia/core';
import { Box, Typography } from '@mui/material';

/* ========================================================================== */

type NFTStatusBarProps = {
  statusText?: string | React.ReactElement;
  showDropShadow?: boolean;
};

export default function NFTStatusBar(props: NFTStatusBarProps) {
  const { statusText, showDropShadow = false } = props;
  const boxShadow = '0px 4px 4px rgba(0, 0, 0, 0.25)';

  return statusText ? (
    <Box
      sx={{
        boxSizing: 'border-box',
        position: 'absolute',
        top: '0',
        left: '0',
        backgroundColor: 'rgba(255, 255, 255, 0.5)',
        boxShadow: `${showDropShadow ? boxShadow : 'none'}`,
        height: '40px',
        width: '100%',
        zIndex: '1',
      }}
    >
      <Flex
        style={{ height: '100%' }}
        alignItems="center"
        justifyContent="center"
      >
        <Typography variant="caption" color="rgba(0,0,0,1)" fontWeight="bold">
          {statusText}
        </Typography>
      </Flex>
    </Box>
  ) : null;
}
