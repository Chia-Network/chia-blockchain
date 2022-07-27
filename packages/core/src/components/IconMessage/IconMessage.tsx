import React, { type ReactNode } from 'react';
import { Typography, type TypographyProps } from '@mui/material';
import Flex from '../Flex';

export type IconMessageProps = TypographyProps & {
  children: ReactNode;
  icon: ReactNode;
};

export default function IconMessage(props: IconMessageProps) {
  const { icon, children, ...rest } = props;

  return (
    <Flex flexDirection="column" gap={1} alignItems="center">
      {icon}
      <Typography variant="body1" align="center" {...rest}>
        {children}
      </Typography>
    </Flex>
  );
}
