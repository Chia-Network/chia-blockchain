import React, { useState, useEffect, ReactNode } from 'react';
import isElectron from 'is-electron';
import { Trans } from '@lingui/macro';
import { ConnectionState } from '@chia/api';
import { useCloseMutation, useGetStateQuery } from '@chia/api-react';
import { Flex, Loading, ServiceHumanName } from '@chia/core';
import LayoutHero from '../layout/LayoutHero';
import { Typography } from '@material-ui/core';

type Props = {
  children: ReactNode;
};

export default function AppState(props: Props) {
  const { children } = props;
  const [close] = useCloseMutation();
  const [closing, setClosing] = useState<boolean>(false);
  const { data: clienState = {}, isLoading: isClientStateLoading } = useGetStateQuery();

  const isConnected = !isClientStateLoading && clienState?.state === ConnectionState.CONNECTED;

  async function handleClose(event) {
    setClosing(true);

    await close({
      force: true,
    });

    event.sender.send('daemon-exited');
  }

  useEffect(() => {
    window.addEventListener('load', () => {
      if (isElectron()) {
        // @ts-ignore
        window.ipcRenderer.on('exit-daemon', handleClose);
      }
    });
  }, []);

  if (closing) {
    return (
      <LayoutHero>
        <Loading center>
          <Trans>Closing down node and server</Trans>
        </Loading>
      </LayoutHero>
    );
  }

  if (!isConnected) {
    const { attempt, startingService } = clienState;

    return (
      <LayoutHero>
        <Loading center>
          {startingService ? (
            <Trans>Starting service {ServiceHumanName[startingService]}</Trans>
          ) : isClientStateLoading || !attempt ? (
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
        </Loading>
      </LayoutHero>
    );
  }

  return (
    <>
      {children}
    </>
  );
}
