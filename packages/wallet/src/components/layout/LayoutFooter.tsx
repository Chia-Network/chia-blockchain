import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex } from '@chia/core';
import styled from 'styled-components';
import { Shell } from 'electron';
import packageJson from '../../../package.json';

const Version = styled.a`
align-self: flex-end;
padding-left: ${({ theme }) => `${theme.spacing(3)}px`};
color: rgb(128, 128, 128);
`;

const SendFeedback = styled.a`
align-self: flex-end;
padding-right: ${({ theme }) => `${theme.spacing(3)}px`};
color: rgb(128, 160, 194);
display: inline;
`;

const Footer = styled(Flex)`
width: 100%;
bottom: 0;
padding-bottom: ${({ theme }) => `${theme.spacing(3)}px`};
`;

async function openSendFeedbackURL(): Promise<void> {
  try {
    const shell: Shell = (window as any).shell;
    await shell.openExternal('https://forms.gle/f19UKU52xtWGwQqH9');
  }
  catch (e) {
    console.error(e);
  }
}

export default function LayoutFooter() {
  const { productName, version } = packageJson;

  return (
    <Footer flexDirection="row" flexGrow={1} justifyContent="space-between">
      <Version>
        {productName} {version}
      </Version>
      <SendFeedback onClick={openSendFeedbackURL}>
        <Trans>Send Feedback</Trans>
      </SendFeedback>
    </Footer>
  )
}