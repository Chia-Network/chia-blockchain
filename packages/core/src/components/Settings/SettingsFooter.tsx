import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex, Link } from '@chia/core';
import { Box, Typography } from '@material-ui/core';
import styled from 'styled-components';
import { Shell } from 'electron';
import { default as walletPackageJson } from '../../../package.json';
import useAppVersion from '../../hooks/useAppVersion';

const { productName } = walletPackageJson;

const StyledRoot = styled(Flex)`
  padding: 1rem;
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

export default function SettingsFooter() {
  const { version } = useAppVersion();

  return (
    <StyledRoot>
      <Typography color="textSecondary" variant="body2">
        {productName} {version}
      </Typography>
      <Box flexGrow={1} />
      <Flex>
        <Link onClick={openFAQURL}>
          <Trans>FAQ</Trans>
        </Link>
        &nbsp;
        <Link onClick={openSendFeedbackURL}>
          <Trans>Send Feedback</Trans>
        </Link>
      </Flex>
    </StyledRoot>
  )
}