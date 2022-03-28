import React, { ReactElement } from 'react';
import { Typography, TypographyProps } from '@mui/material';
import Flex from '../Flex';
import TooltipIcon from '../TooltipIcon';

type Props = TypographyProps & {
  title: ReactElement<any>;
};

export default function TooltipTypography(props: Props) {
  const { title, ...rest } = props;

  return (
    <Flex alignItems="center" gap={1}>
      <Typography {...rest} />
      <TooltipIcon>{title}</TooltipIcon>
    </Flex>
  );
}
