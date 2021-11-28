import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex } from '@chia/core';
import styled from 'styled-components';
import { Remote, Shell } from 'electron';
import { default as walletPackageJson } from '../../../package.json';

const Version = styled.a`
align-self: flex-end;
padding-left: ${({ theme }) => `${theme.spacing(3)}px`};
color: rgb(128, 128, 128);
`;

const FAQ = styled.a`
align-self: flex-end;
color: rgb(128, 160, 194);
`;

const SendFeedback = styled.a`
align-self: flex-end;
padding-right: ${({ theme }) => `${theme.spacing(3)}px`};
color: rgb(128, 160, 194);
`;

const Footer = styled(Flex)`
width: 100%;
bottom: 0;
padding-bottom: ${({ theme }) => `${theme.spacing(3)}px`};
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
  const remote: Remote = (window as any).remote;
  const version = remote.app.getVersion();
  const { productName } = walletPackageJson;

  return (
    <Footer flexDirection="row" flexGrow={1} justifyContent="space-between">
      <Version>
        {productName} {version}
      </Version>
      <Flex flexDirection="row" gap={2}>
        <FAQ onClick={openFAQURL}>
          <Trans>FAQ</Trans>
        </FAQ>
        <SendFeedback onClick={openSendFeedbackURL}>
          <Trans>Send Feedback</Trans>
        </SendFeedback>
      </Flex>
    </Footer>
  )
}