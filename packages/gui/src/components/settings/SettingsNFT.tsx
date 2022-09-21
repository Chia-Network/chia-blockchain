import React from 'react';
import { Trans } from '@lingui/macro';
import { Grid, Box, Button } from '@mui/material';
import styled from 'styled-components';

import { Flex, SettingsLabel } from '@chia/core';
import { Switch, FormGroup, FormControlLabel } from '@mui/material';
import useHideObjectionableContent from '../../hooks/useHideObjectionableContent';
import { useLocalStorage } from '@chia/core';
import { AlertDialog, useOpenDialog } from '@chia/core';
import { FormatBytes } from '@chia/core';
import LimitCacheSize from './LimitCacheSize';

export default function SettingsGeneral() {
  const [hideObjectionableContent, setHideObjectionableContent] =
    useHideObjectionableContent();

  function handleChangeHideObjectionableContent(
    event: React.ChangeEvent<HTMLInputElement>,
  ) {
    setHideObjectionableContent(event.target.checked);
  }

  const [cacheFolder, setCacheFolder] = useLocalStorage('cacheFolder');
  const [defaultCacheFolder, setDefaultCacheFolder] = React.useState();
  const [cacheSize, setCacheSize] = React.useState(0);
  const openDialog = useOpenDialog();

  React.useEffect(() => {
    (async () => {
      setDefaultCacheFolder(
        await (window as any).ipcRenderer.invoke('getDefaultCacheFolder'),
      );
      setCacheSize(await (window as any).ipcRenderer.invoke('getCacheSize'));
    })();
  }, []);

  async function forceUpdateCacheSize() {
    setCacheSize(await (window as any).ipcRenderer.invoke('getCacheSize'));
  }

  const CacheTable = styled.div`
    display: table;
    margin-top: 15px;
    font-size: 15px;
    max-width: 10px;
    > div {
      display: table-row;
      > div {
        display: table-cell;
        padding: 5px 20px 5px 0;
        white-space: nowrap;
      }
      > div:nth-child(2) {
        font-weight: bold;
      }
    }
  `;

  function renderCacheFolder() {
    if (cacheFolder) {
      return cacheFolder;
    }
    return defaultCacheFolder;
  }

  function renderCacheSize() {
    return <FormatBytes value={cacheSize} precision={3} />;
  }

  async function chooseAnotherFolder() {
    const newFolder = await (window as any).ipcRenderer.invoke(
      'selectCacheFolder',
    );

    if (!newFolder.canceled) {
      const folderFileCount = await (window as any).ipcRenderer.invoke(
        'isNewFolderEmtpy',
        newFolder.filePaths[0],
      );

      if (folderFileCount > 0) {
        openDialog(
          <AlertDialog title={<Trans>Error</Trans>}>
            <Trans>Please select an empty folder</Trans>
          </AlertDialog>,
        );
      } else {
        setCacheFolder(newFolder.filePaths[0]);
      }
    }
  }

  return (
    <Grid container>
      <Grid item xs={12} sm={6} lg={3}>
        <Flex flexDirection="column" gap={1}>
          <SettingsLabel>
            <Trans>Gallery Management</Trans>
          </SettingsLabel>

          <FormGroup>
            <FormControlLabel
              control={
                <Switch
                  checked={hideObjectionableContent}
                  onChange={handleChangeHideObjectionableContent}
                />
              }
              label={<Trans>Hide objectionable content</Trans>}
            />
            <Box sx={{ m: 2 }} />

            <SettingsLabel>
              <Trans>Cache</Trans>
            </SettingsLabel>

            <CacheTable>
              <div>
                <div>
                  <Trans>Occupied space</Trans>
                </div>
                <div>{renderCacheSize()}</div>
                <div>&nbsp;</div>
              </div>
              <div>
                <div>
                  <Trans>Local folder</Trans>
                </div>
                <div>{renderCacheFolder()}</div>
                <div>
                  <Button
                    onClick={chooseAnotherFolder}
                    color="primary"
                    variant="outlined"
                    size="small"
                  >
                    <Trans>Change</Trans>
                  </Button>
                </div>
              </div>
              <div>
                <div>
                  <Trans>Limit cache size</Trans>
                </div>
                <div>
                  <LimitCacheSize forceUpdateCacheSize={forceUpdateCacheSize} />
                </div>
                <div></div>
              </div>
            </CacheTable>
          </FormGroup>
        </Flex>
      </Grid>
    </Grid>
  );
}
