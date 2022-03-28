import React, { type ReactNode } from 'react';
import { Trans } from '@lingui/macro';
import useDarkMode from 'use-dark-mode';
import { type Shell } from 'electron';
import Button from '../Button';
import Link from '../Link';
import { ButtonGroup } from '@mui/material';
import { 
  WbSunny as WbSunnyIcon, 
  NightsStay as NightsStayIcon,
  AccountBalanceWallet as AccountBalanceWalletIcon,
  EnergySavingsLeaf as EcoIcon,
} from '@mui/icons-material';
import useMode from '../../hooks/useMode';
import SettingsLabel from './SettingsLabel';
import Flex from '../Flex';
import Mode from '../../constants/Mode';
import LocaleToggle from '../LocaleToggle';
import useShowError from '../../hooks/useShowError';

export type SettingsAppProps = {
  children?: ReactNode;
};

export default function SettingsApp(props: SettingsAppProps) {
  const { children } = props;

  const [mode, setMode] = useMode();
  const showError = useShowError();
  const { enable, disable, value: darkMode } = useDarkMode();

  function handleSetFarmingMode() {
    setMode(Mode.FARMING);
  }

  function handleSetWalletMode() {
    setMode(Mode.WALLET);
  }

  async function handleOpenFAQURL(): Promise<void> {
    try {
      const shell: Shell = (window as any).shell;
      await shell.openExternal('https://github.com/Chia-Network/chia-blockchain/wiki/FAQ');
    } catch (error: any) {
      showError(error);
    }
  }
  
  async function handleOpenSendFeedbackURL(): Promise<void> {
    try {
      const shell: Shell = (window as any).shell;
      await shell.openExternal('https://feedback.chia.net/lightwallet');
    } catch (error: any) {
      showError(error);
    }
  }

  return (
    <Flex flexDirection="column" gap={3}>
      <Flex flexDirection="column" gap={1}>
        <SettingsLabel>
          <Trans>Mode</Trans>
        </SettingsLabel>
        <ButtonGroup fullWidth>
          <Button startIcon={<EcoIcon />} selected={mode === Mode.FARMING} onClick={handleSetFarmingMode}>
            <Trans>Farming</Trans>
          </Button>
          <Button startIcon={<AccountBalanceWalletIcon />} selected={mode === Mode.WALLET} onClick={handleSetWalletMode}>
            <Trans>Wallet</Trans>
          </Button>
        </ButtonGroup>
      </Flex>

      <Flex flexDirection="column" gap={1}>
        <SettingsLabel>
          <Trans>Appearance</Trans>
        </SettingsLabel>
        <ButtonGroup fullWidth>
          <Button startIcon={<WbSunnyIcon />} selected={!darkMode} onClick={() => disable()}>
            <Trans>Light</Trans>
          </Button>
          <Button startIcon={<NightsStayIcon />} selected={darkMode} onClick={() => enable()}>
            <Trans>Dark</Trans>
          </Button>
        </ButtonGroup>
      </Flex>

      <Flex flexDirection="column" gap={1}>
        <SettingsLabel>
          <Trans>Language</Trans>
        </SettingsLabel>
        <LocaleToggle 
          variant="outlined"
        />
      </Flex>

      {children}

      <Flex flexDirection="column" gap={1}>
        <SettingsLabel>
          <Trans>Help</Trans>
        </SettingsLabel>
        <Flex flexDirection="column">
          <Link onClick={handleOpenFAQURL}>
            <Trans>Frequently Asked Questions</Trans>
          </Link>
          <Link onClick={handleOpenSendFeedbackURL}>
            <Trans>Send Feedback</Trans>
          </Link>
        </Flex>
      </Flex>
    </Flex>
  );
}