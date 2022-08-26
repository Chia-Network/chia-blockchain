import React, { useState, useEffect, ReactNode, useMemo } from 'react';
import isElectron from 'is-electron';
import { Trans } from '@lingui/macro';
import {
  ConnectionState,
  ServiceHumanName,
  ServiceName,
  PassphrasePromptReason,
} from '@chia/api';
import {
  useCloseMutation,
  useGetStateQuery,
  useGetKeyringStatusQuery,
  useServices,
} from '@chia/api-react';
import {
  Flex,
  LayoutHero,
  LayoutLoading,
  useMode,
  useIsSimulator,
} from '@chia/core';
import { Typography, Collapse } from '@mui/material';
import AppKeyringMigrator from './AppKeyringMigrator';
import AppPassPrompt from './AppPassPrompt';
import AppSelectMode from './AppSelectMode';
import ModeServices, { SimulatorServices } from '../../constants/ModeServices';

const ALL_SERVICES = [
  ServiceName.WALLET,
  ServiceName.FULL_NODE,
  ServiceName.FARMER,
  ServiceName.HARVESTER,
  ServiceName.SIMULATOR,
  ServiceName.DATALAYER,
];

type Props = {
  children: ReactNode;
};

export default function AppState(props: Props) {
  const { children } = props;
  const [close] = useCloseMutation();
  const [closing, setClosing] = useState<boolean>(false);
  const { data: clienState = {}, isLoading: isClientStateLoading } =
    useGetStateQuery();
  const { data: keyringStatus, isLoading: isLoadingKeyringStatus } =
    useGetKeyringStatusQuery();
  const [mode] = useMode();
  const isSimulator = useIsSimulator();

  const runServices = useMemo<ServiceName[] | undefined>(() => {
    if (mode) {
      if (isSimulator) {
        return SimulatorServices;
      }

      return ModeServices[mode];
    }

    return undefined;
  }, [mode, isSimulator]);

  const isKeyringReady = !!keyringStatus && !keyringStatus.isKeyringLocked;

  const servicesState = useServices(ALL_SERVICES, {
    keepRunning: !closing ? runServices : [],
    disabled: !isKeyringReady,
  });

  const allServicesRunning = useMemo<boolean>(() => {
    if (!runServices) {
      return false;
    }

    const specificRunningServiceStates = servicesState.running.filter(
      (serviceState) => runServices.includes(serviceState.service),
    );

    return specificRunningServiceStates.length === runServices.length;
  }, [servicesState, runServices]);

  const isConnected =
    !isClientStateLoading && clienState?.state === ConnectionState.CONNECTED;

  async function handleClose(event) {
    if (closing) {
      return;
    }

    setClosing(true);

    await close({
      force: true,
    }).unwrap();

    event.sender.send('daemon-exited');
  }

  useEffect(() => {
    if (isElectron()) {
      // @ts-ignore
      window.ipcRenderer.on('exit-daemon', handleClose);
      return () => {
        // @ts-ignore
        window.ipcRenderer.off('exit-daemon', handleClose);
      };
    }
  }, []);

  if (closing) {
    return (
      <LayoutLoading hideSettings>
        <Flex flexDirection="column" gap={2}>
          <Typography variant="body1" align="center">
            <Trans>Closing down services</Trans>
          </Typography>
          <Flex flexDirection="column" gap={0.5}>
            {!!ALL_SERVICES &&
              ALL_SERVICES.map((service) => (
                <Collapse
                  key={service}
                  in={!!clienState?.startedServices.includes(service)}
                  timeout={{ enter: 0, exit: 1000 }}
                >
                  <Typography
                    variant="body1"
                    color="textSecondary"
                    align="center"
                  >
                    {ServiceHumanName[service]}
                  </Typography>
                </Collapse>
              ))}
          </Flex>
        </Flex>
      </LayoutLoading>
    );
  }

  if (isLoadingKeyringStatus || !keyringStatus) {
    return (
      <LayoutLoading>
        <Trans>Loading keyring status</Trans>
      </LayoutLoading>
    );
  }

  const { needsMigration, isKeyringLocked } = keyringStatus;
  if (needsMigration) {
    return (
      <LayoutHero>
        <AppKeyringMigrator />
      </LayoutHero>
    );
  }

  if (isKeyringLocked) {
    return (
      <LayoutHero>
        <AppPassPrompt reason={PassphrasePromptReason.KEYRING_LOCKED} />
      </LayoutHero>
    );
  }

  if (!isConnected) {
    const { attempt } = clienState;
    return (
      <LayoutLoading>
        {!attempt ? (
          <Trans>Connecting to daemon</Trans>
        ) : (
          <Flex flexDirection="column" gap={1}>
            <Typography variant="body1" align="center">
              <Trans>Connecting to daemon</Trans>
            </Typography>
            <Typography variant="body1" align="center" color="textSecondary">
              <Trans>Attempt {attempt}</Trans>
            </Typography>
          </Flex>
        )}
      </LayoutLoading>
    );
  }

  if (!mode) {
    return (
      <LayoutHero maxWidth="md">
        <AppSelectMode />
      </LayoutHero>
    );
  }

  if (!allServicesRunning) {
    return (
      <LayoutLoading>
        <Flex flexDirection="column" gap={2}>
          <Typography variant="body1" align="center">
            <Trans>Starting services</Trans>
          </Typography>
          <Flex flexDirection="column" gap={0.5}>
            {!!runServices &&
              runServices.map((service) => (
                <Collapse
                  key={service}
                  in={
                    !servicesState.running.find(
                      (state) => state.service === service,
                    )
                  }
                  timeout={{ enter: 0, exit: 1000 }}
                >
                  <Typography
                    variant="body1"
                    color="textSecondary"
                    align="center"
                  >
                    {ServiceHumanName[service]}
                  </Typography>
                </Collapse>
              ))}
          </Flex>
        </Flex>
      </LayoutLoading>
    );
  }

  return <>{children}</>;
}
