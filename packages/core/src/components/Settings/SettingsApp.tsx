import React, { ReactNode } from 'react';
import { Trans } from '@lingui/macro';
import useDarkMode from 'use-dark-mode';
import Button from '../Button';
import { ButtonGroup } from '@material-ui/core';
import { 
  WbSunny as WbSunnyIcon, 
  NightsStay as NightsStayIcon,
  AccountBalanceWallet as AccountBalanceWalletIcon,
  Eco as EcoIcon,
} from '@material-ui/icons';
import useMode from '../../hooks/useMode';
import SettingsLabel from './SettingsLabel';
import Flex from '../Flex';
import Mode from '../../constants/Mode';
import LocaleToggle from '../LocaleToggle';

export type SettingsAppProps = {
  children?: ReactNode;
};

export default function SettingsApp(props: SettingsAppProps) {
  const { children } = props;

  const [mode, setMode] = useMode();
  const { enable, disable, value: darkMode } = useDarkMode();

  function handleSetFarmingMode() {
    setMode(Mode.FARMING);
  }

  function handleSetWalletMode() {
    setMode(Mode.WALLET);
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
    </Flex>
  );
}