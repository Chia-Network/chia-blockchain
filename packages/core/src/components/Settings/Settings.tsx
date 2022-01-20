import React, { type ReactNode, useState } from 'react';
import { Trans } from '@lingui/macro';
import styled from 'styled-components';
import { Box, Drawer, Typography, IconButton, Divider } from '@material-ui/core';
import { Settings as SettingsIcon, Close as CloseIcon } from '@material-ui/icons';
import Flex from '../Flex';
import Tooltip from '../Tooltip';
import SettingsApp from './SettingsApp';
import SettingsFooter from './SettingsFooter';

const StyledHeader = styled(Box)`
  padding: 0.5rem 1rem;
  width: 360px;
`;

const StyledBody = styled(Box)`
  padding: 1rem 1rem;
  flex-grow: 1;
  overflow: auto;
`;

export type SettingsProps = {
  children?: ReactNode;
};

export default function Settings(props: SettingsProps) {
  const { children = <SettingsApp /> } = props;
  const [open, setOpen] = useState<boolean>(false);

  function handleOpen(event: React.MouseEvent<HTMLButtonElement>) {
    if (event.type === 'keydown' && (event.key === 'Tab' || event.key === 'Shift')) {
      return;
    }

    setOpen(true);
  }

  function handleClose(event) {
    if (event.type === 'keydown' && (event.key === 'Tab' || event.key === 'Shift')) {
      return;
    }
    
    setOpen(false);
  }

  return (
    <>
      <Tooltip title={<Trans>Settings</Trans>}>
      <IconButton color="inherit" onClick={handleOpen} disableFocusRipple>
        <SettingsIcon />
      </IconButton>
      </Tooltip>
      <Drawer anchor="right" open={open} onClose={handleClose}>
        <Flex flexDirection="column" height="100%">
          <StyledHeader>
            <Flex gap={1} justifyContent="space-between" alignItems="center">
              <Typography variant="h6">
                <Trans>
                  Settings
                </Trans>
              </Typography>
              <IconButton color="inherit" onClick={handleClose}>
                <CloseIcon />
              </IconButton>
            </Flex>
          </StyledHeader>
          <Divider />
          <StyledBody>
            {children}
          </StyledBody>
          <SettingsFooter />
        </Flex>
      </Drawer>
    </>
  );
}
