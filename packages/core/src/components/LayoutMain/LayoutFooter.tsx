import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex } from '@chia/core';
import { Typography } from '@material-ui/core';
import styled from 'styled-components';
import { Shell } from 'electron';
import { default as walletPackageJson } from '../../../package.json';
import useAppVersion from '../../hooks/useAppVersion';

const { productName } = walletPackageJson;

const FAQ = styled.a`
color: rgb(128, 160, 194);
`;

const SendFeedback = styled.a`
color: rgb(128, 160, 194);
`;

async function openFAQURL(): Promise<void> {
  try {
    const shell: Shell = (window as any).shell;
    await shell.openExternal('https://github.com/Chia-Network/chia-blockchain/wiki/FAQ');
  }
  catch (e) {
    console.error(e);
  }
}

async function openSendFeedbackURL(): Promise<void> {
  try {
    const shell: Shell = (window as any).shell;
    await shell.openExternal('https://feedback.chia.net/lightwallet');
  }
  catch (e) {
    console.error(e);
  }
}

export default function LayoutFooter() {
  const { version } = useAppVersion();

  return (
    <Flex flexDirection="row" flexGrow={1} justifyContent="space-between">
      <Typography color="textSecondary" variant="body2">
        {productName} {version}
      </Typography>
      <Flex gap={2}>
        <FAQ onClick={openFAQURL}>
          <Trans>FAQ</Trans>
        </FAQ>
        <SendFeedback onClick={openSendFeedbackURL}>
          <Trans>Send Feedback</Trans>
        </SendFeedback>
      </Flex>
    </Flex>
  )
}