import React from 'react';
import { Trans } from '@lingui/macro';
import {
  Dropzone,
  Flex,
  useOpenDialog,
  useSerializedNavigationState,
  useShowError,
} from '@chia/core';
import { Box, Card, Typography } from '@mui/material';
import { useGetOfferSummaryMutation } from '@chia/api-react';
import { type OfferSummaryRecord } from '@chia/api';
// import OfferDataEntryDialog from '../offers/OfferDataEntryDialog';
import fs, { Stats } from 'fs';
// import { IpcRenderer } from 'electron';
import { useHotkeys } from 'react-hotkeys-hook';
import ImportOfferBackground from './images/importOfferBackground.svg';
import OfferFileIcon from './images/offerFileIcon.svg';

function Background(props) {
  const { children } = props;
  return (
    <Box position="relative" p={3}>
      <Box
        position="absolute"
        left={0}
        right={0}
        top={0}
        bottom={0}
        display="flex"
        alignItems="center"
        justifyContent="center"
        marginY={-2}
      >
        <ImportOfferBackground height="100%" />
      </Box>
      {children}
    </Box>
  );
}

export default function OfferBuilderImport() {
  const { navigate } = useSerializedNavigationState();
  const [getOfferSummary] = useGetOfferSummaryMutation();
  const openDialog = useOpenDialog();
  const errorDialog = useShowError();
  const [isParsing, setIsParsing] = React.useState<boolean>(false);

  function parseOfferData(
    data: string,
  ): [
    offerData: string | undefined,
    leadingText: string | undefined,
    trailingText: string | undefined,
  ] {
    // Parse raw offer data looking for the bech32-encoded offer data and any surrounding text.
    const matches = data.match(
      /(?<leading>.*)(?<offer>offer1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]+)(?<trailing>.*)/s,
    );
    return [
      matches?.groups?.offer,
      matches?.groups?.leading,
      matches?.groups?.trailing,
    ];
  }

  async function parseOfferSummary(
    rawOfferData: string,
    offerFilePath: string | undefined,
  ) {
    const [offerData /*, leadingText, trailingText*/] =
      parseOfferData(rawOfferData);
    let offerSummary: OfferSummaryRecord | undefined;

    if (offerData) {
      const { data: response } = await getOfferSummary(offerData);
      const { summary, success } = response;

      if (success) {
        offerSummary = summary;
      }
    } else {
      console.warn('Unable to parse offer data');
    }

    console.log({ offerData, offerSummary, offerFilePath, imported: true });

    if (offerSummary) {
      navigate('/dashboard/offers/view', {
        state: {
          offerData,
          offerSummary,
          offerFilePath,
          imported: true,
          referrerPath: '/dashboard/offers',
        },
      });
    } else {
      errorDialog(new Error('Could not parse offer data'));
    }
  }

  async function handleOpen(offerFilePath: string) {
    async function continueOpen(stats: Stats) {
      try {
        if (stats.size > 1024 * 1024) {
          errorDialog(new Error('Offer file is too large (> 1MB)'));
        } else {
          const offerData = fs.readFileSync(offerFilePath, 'utf8');

          await parseOfferSummary(offerData, offerFilePath);
        }
      } catch (e) {
        errorDialog(e);
      } finally {
        setIsParsing(false);
      }
    }

    setIsParsing(true);

    fs.stat(offerFilePath, (err, stats) => {
      if (err) {
        errorDialog(err);
      } else {
        continueOpen(stats);
      }
    });
  }

  async function handleDrop(acceptedFiles: [File]) {
    if (acceptedFiles.length !== 1) {
      errorDialog(new Error('Please drop one offer file at a time'));
    } else {
      handleOpen(acceptedFiles[0].path);
    }
  }

  /*
  async function handlePasteOfferData() {
    const offerData = await openDialog(<OfferDataEntryDialog />);

    if (offerData) {
      setIsParsing(true);

      try {
        await parseOfferSummary(offerData, undefined);
      } catch (e) {
        errorDialog(e);
      } finally {
        setIsParsing(false);
      }
    }
  }

  async function handleSelectOfferFile() {
    const dialogOptions = {
      filters: [{ name: 'Offer Files', extensions: ['offer'] }],
    } as Electron.OpenDialogOptions;
    const ipcRenderer: IpcRenderer = (window as any).ipcRenderer;
    const { canceled, filePaths } = await ipcRenderer.invoke(
      'showOpenDialog',
      dialogOptions,
    );
    if (!canceled && filePaths?.length) {
      handleOpen(filePaths[0]);
    }
  }
  */

  async function pasteParse(text: string) {
    try {
      await parseOfferSummary(text, undefined);
    } catch (e) {
      errorDialog(e);
    } finally {
      setIsParsing(false);
    }
  }

  const isMac = /(Mac|iPhone|iPod|iPad)/i.test(navigator.platform);
  const hotKey = isMac ? 'cmd+v' : 'ctrl+v';

  useHotkeys(hotKey, () => {
    navigator.clipboard
      .readText()
      .then((text) => {
        pasteParse(text);
      })
      .catch((err) => {
        console.log('Error during paste from clipboard', err);
      });
  });

  return (
    <Card
      variant="outlined"
      sx={{
        height: '100%',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        cursor: 'pointer',
      }}
    >
      <Dropzone
        maxFiles={1}
        onDrop={handleDrop}
        processing={isParsing}
        background={Background}
      >
        <Flex flexDirection="column" alignItems="center">
          <OfferFileIcon />
          <Typography color="textSecondary" variant="h6" textAlign="center">
            <Trans>Drag & Drop an Offer File, Paste </Trans>
            {isMac ? (
              <Trans>(⌘V) a blob</Trans>
            ) : (
              <Trans>(Ctrl-V) a blob</Trans>
            )}
          </Typography>
          <Typography color="textSecondary" textAlign="center">
            <Trans>
              or <span style={{ color: '#5ECE71' }}>browse</span> on your
              computer
            </Trans>
          </Typography>
        </Flex>
      </Dropzone>
    </Card>
  );
}
