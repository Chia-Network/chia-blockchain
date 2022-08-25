import React from 'react';
import { Box, Tooltip as BaseTooltip, TooltipProps } from '@mui/material';
import Flex from '../Flex';
import CopyToClipboard from '../CopyToClipboard';

type Props = TooltipProps & {
  copyToClipboard?: boolean;
  maxWidth?: any;
  disableInteractive?: boolean;
};

export default function Tooltip(props: Props) {
  const {
    copyToClipboard = false,
    title,
    maxWidth = 200,
    disableInteractive,
    children,
    ...rest
  } = props;

  const titleContent = copyToClipboard ? (
    <Flex alignItems="center" gap={1}>
      <Box maxWidth={maxWidth}>{title}</Box>
      <CopyToClipboard value={title} fontSize="small" invertColor />
    </Flex>
  ) : (
    title
  );

  return (
    <BaseTooltip
      title={titleContent}
      disableInteractive={!copyToClipboard && disableInteractive}
      {...rest}
    >
      {Array.isArray(children) ? <span>{children}</span> : children}
    </BaseTooltip>
  );
}
