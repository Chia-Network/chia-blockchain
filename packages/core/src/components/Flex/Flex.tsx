import React from 'react';
import { Stack, type StackProps } from '@mui/material';

export type FlexProps = StackProps & {
  flexDirection?: 'row' | 'column';
  inline?: boolean;
};

export default function Flex(props: FlexProps) {
  const { flexDirection = 'row', direction, inline, sx, ...rest } = props;

  const computedDirection = direction ?? flexDirection;

  return (
    <Stack
      direction={computedDirection}
      sx={{
        display: inline ? 'inline-flex' : 'flex',
        ...sx,
      }}
      {...rest}
    />
  );
}
