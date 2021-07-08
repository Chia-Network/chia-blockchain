import React from 'react';
import { Box, Tooltip as BaseTooltip, TooltipProps } from '@material-ui/core';
import Flex from '../Flex';
import CopyToClipboard from '../CopyToClipboard';

type Props = TooltipProps & {
  copyToClipboard?: boolean;
  maxWidth?: any;
};

export default function Tooltip(props: Props) {
  const { copyToClipboard, title, maxWidth, interactive, ...rest } = props;

  const titleContent = copyToClipboard ? (
    <Flex alignItems="center" gap={1}>
      <Box maxWidth={maxWidth}>{title}</Box>
      <CopyToClipboard value={title} fontSize="small" />
    </Flex>
  ) : (
    title
  );

  const currentInteractive = copyToClipboard || interactive;

  return (
    <BaseTooltip
      title={titleContent}
      interactive={currentInteractive}
      {...rest}
    />
  );
}

Tooltip.defaultProps = {
  copyToClipboard: false,
  maxWidth: 200,
};
