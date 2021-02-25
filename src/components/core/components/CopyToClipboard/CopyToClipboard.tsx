import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import { useCopyToClipboard } from 'react-use';
import { IconButton } from '@chia/core';
import { Tooltip } from '@material-ui/core';
import { Assignment as AssignmentIcon } from '@material-ui/icons';
// @ts-ignore
import { useTimeout } from 'react-use-timeout';

type Props = {
  value: string;
  fontSize: 'default' | 'small' | 'large';
  clearCopiedDelay: number;
};

export default function CopyToClipboard(props: Props) {
  const { value, fontSize, clearCopiedDelay } = props;
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

  const tooltipTitle = copied 
    ? <Trans>Copied</Trans>
    : <Trans>Copy to Clipboard</Trans>

  return (
    <Tooltip title={tooltipTitle}>
      <IconButton>
        <AssignmentIcon onClick={handleCopy} fontSize={fontSize} />
      </IconButton>
    </Tooltip>
  );
}

CopyToClipboard.defaultProps = {
  fontSize: 'default',
  clearCopiedDelay: 1000,
};
