import React, { useState, useEffect, ReactNode } from 'react';
import isElectron from 'is-electron';
import { Trans } from '@lingui/macro';
import { useCloseMutation } from '@chia/api-react';
import { Loading } from '@chia/core';
import LayoutHero from '../layout/LayoutHero';

type Props = {
  children: ReactNode;
};

export default function AppDisconnect(props: Props) {
  const { children } = props;
  const [close] = useCloseMutation();
  const [closing, setClosing] = useState<boolean>(false);

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

  return (
    <>
      {children}
    </>
  );
}
