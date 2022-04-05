import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import { useCopyToClipboard } from 'react-use';
import { Tooltip, IconButton } from '@mui/material';
import { Assignment as AssignmentIcon } from '@mui/icons-material';
// @ts-ignore
import { useTimeout } from 'react-use-timeout';
import { styled } from '@mui/system';

const StyledAssignmentIcon = styled(AssignmentIcon)(({ theme, invertColor }) => `
  color: ${invertColor ? theme.palette.common.white : theme.palette.text.primary};
`);

export type CopyToClipboardProps = {
  value: string;
  fontSize?: 'medium' | 'small' | 'large' | 'inherit';
  size: 'small' | 'medium';
  clearCopiedDelay: number;
  invertColor?: boolean;
};

export default function CopyToClipboard(props: CopyToClipboardProps) {
  const { value, size = 'small', fontSize = 'medium', clearCopiedDelay = 1000, invertColor = false } = props;
  const [, copyToClipboard] = useCopyToClipboard();
  const [copied, setCopied] = useState<boolean>(false);
  const timeout = useTimeout(() => {
    setCopied(false);
  }, clearCopiedDelay);

  function handleCopy() {
    copyToClipboard(value);
    setCopied(true);
    timeout.start();
  }

  const tooltipTitle = copied ? (
    <Trans>Copied</Trans>
  ) : (
    <Trans>Copy to Clipboard</Trans>
  );

  return (
    <Tooltip title={tooltipTitle}>
      <IconButton onClick={handleCopy} size={size}>
        <StyledAssignmentIcon fontSize={fontSize} invertColor={invertColor} />
      </IconButton>
    </Tooltip>
  );
}
