import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import { useCopyToClipboard } from 'react-use';
import { Tooltip, IconButton } from '@material-ui/core';
import { Assignment as AssignmentIcon } from '@material-ui/icons';
// @ts-ignore
import { useTimeout } from 'react-use-timeout';

type Props = {
  value: string;
  fontSize: 'default' | 'small' | 'large';
  size: 'small' | 'medium';
  clearCopiedDelay: number;
};

export default function CopyToClipboard(props: Props) {
  const { value, size, fontSize, clearCopiedDelay } = props;
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
        <AssignmentIcon fontSize={fontSize} />
      </IconButton>
    </Tooltip>
  );
}

CopyToClipboard.defaultProps = {
  fontSize: 'medium',
  clearCopiedDelay: 1000,
  size: 'small',
};
