import React, { useState, useEffect, ReactNode, useMemo } from 'react';
import isElectron from 'is-electron';
import { Trans } from '@lingui/macro';
import { ConnectionState, ServiceHumanName, ServiceName, PassphrasePromptReason } from '@chia/api';
import { useCloseMutation, useGetStateQuery, useGetKeyringStatusQuery, useClientStartServiceMutation } from '@chia/api-react';
import { Flex, useSkipMigration, LayoutHero, LayoutLoading, sleep } from '@chia/core';
import { Typography, Collapse } from '@material-ui/core';
import AppKeyringMigrator from './AppKeyringMigrator';
import AppPassPrompt from './AppPassPrompt';
import config from '../../config/config';

const services = config.local_test ? [
  ServiceName.WALLET,
  ServiceName.SIMULATOR,
] : [
  ServiceName.WALLET, 
  ServiceName.FULL_NODE,
  ServiceName.FARMER,
  ServiceName.HARVESTER,
];

async function waitForConfig() {
  while(true) {
    const config = window.ipcRenderer.invoke('getConfig');
    if (config) {
      return config;
    }

    await sleep(50);
  }
}

type Props = {
  children: ReactNode;
};

export default function AppState(props: Props) {
  const { children } = props;
  const [close] = useCloseMutation();
  const [closing, setClosing] = useState<boolean>(false);
  const [startService] = useClientStartServiceMutation();
  const { data: clienState = {}, isLoading: isClientStateLoading } = useGetStateQuery();
  const { data: keyringStatus, isLoading: isLoadingKeyringStatus, error } = useGetKeyringStatusQuery();
  const [isMigrationSkipped] = useSkipMigration();

  const isConnected = !isClientStateLoading && clienState?.state === ConnectionState.CONNECTED;

  const [runningServices, setRunningServices] = useState<Object>({});

  const runningServicesCount = useMemo(() => {
    return Object
      .values(runningServices)
      .filter(isRunning => !!isRunning)
      .length;
  }, [runningServices]);

  const allServicesRunning = services.length === runningServicesCount;

  async function loadAllServices() {
    await Promise.all(services.map(async (service) => {
      await startService({
        service,
      }).unwrap();

      setRunningServices((oldValue) => ({
        ...oldValue,
        [service]: true,
      }));
    }));
  }
  
  useEffect(() => {
    if (!!keyringStatus && !keyringStatus.isKeyringLocked && !allServicesRunning) {
      loadAllServices();
    }
  }, [keyringStatus?.isKeyringLocked, allServicesRunning]);

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
      <LayoutLoading>
        <Trans>Closing down node and server</Trans>
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
  if (needsMigration && !isMigrationSkipped) {
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

  if (!allServicesRunning) {
    return (
      <LayoutLoading>
        <Flex flexDirection="column" gap={2}> 
          <Typography variant="body1" align="center">
            <Trans>Starting services</Trans>
          </Typography>
          <Flex flexDirection="column" gap={0.5}>
            {services.map((service) => (
              <Collapse key={service} in={!runningServices[service]} timeout={{ enter: 0, exit: 1000 }}>
                <Typography variant="body1" color="textSecondary"  align="center">
                  {ServiceHumanName[service]}
                </Typography>
              </Collapse>
            ))}
          </Flex>
        </Flex>
      </LayoutLoading>
    );
  }

  return (
    <>
      {children}
    </>
  );
}
