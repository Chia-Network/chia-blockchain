import React from 'react';
import { useHistory } from 'react-router-dom';
import { Trans } from '@lingui/macro';
import { Back, Card, Dropzone, Flex, useOpenDialog, useShowError } from '@chia/core';
import { Button, Grid, Typography } from '@material-ui/core';
import { useGetOfferSummaryMutation } from '@chia/api-react';
import OfferDataEntryDialog from './OfferDataEntryDialog';
import OfferSummaryRecord from '../../../types/OfferSummaryRecord';
import fs, { Stats } from 'fs';

function SelectOfferFile() {
  const history = useHistory();
  const [getOfferSummary] = useGetOfferSummaryMutation();
  const openDialog = useOpenDialog();
  const errorDialog = useShowError();
  const [isParsing, setIsParsing] = React.useState<boolean>(false);

  function parseOfferData(data: string): [offerData: string | undefined, leadingText: string | undefined, trailingText: string | undefined] {
    // Parse raw offer data looking for the bech32-encoded offer data and any surrounding text.
    const matches = data.match(/(?<leading>.*)(?<offer>offer1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]+)(?<trailing>.*)/s)
    return [matches?.groups?.offer, matches?.groups?.leading, matches?.groups?.trailing];
  }

  async function parseOfferSummary(rawOfferData: string, offerFilePath: string | undefined) {
    const [offerData /*, leadingText, trailingText*/] = parseOfferData(rawOfferData);
    let offerSummary: OfferSummaryRecord | undefined;

    if (offerData) {
      const { data: response } = await getOfferSummary(offerData);
      const { summary, success } = response;

      if (success) {
        offerSummary = summary;
      }
    }
    else {
      console.warn("Unable to parse offer data");
    }

    if (offerSummary) {
      history.push('/dashboard/wallets/offers/view', { offerData, offerSummary, offerFilePath, imported: true });
    }
    else {
      errorDialog(new Error("Could not parse offer data"));
    }
  }

  async function handleOpen(offerFilePath: string) {
    async function continueOpen(stats: Stats) {
      try {
        if (stats.size > 1024 * 1024) {
          errorDialog(new Error("Offer file is too large (> 1MB)"));
        }
        else {
          const offerData = fs.readFileSync(offerFilePath, 'utf8');

          await parseOfferSummary(offerData, offerFilePath);
        }
      }
      catch (e) {
        errorDialog(e);
      }
      finally {
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
      errorDialog(new Error("Please drop one offer file at a time"));
    }
    else {
      handleOpen(acceptedFiles[0].path);
    }
  }

  async function handlePasteOfferData() {
    const offerData = await openDialog((
      <OfferDataEntryDialog />
    ));

    if (offerData) {
      setIsParsing(true);

      try {
        await parseOfferSummary(offerData, undefined);
      }
      catch (e) {
        errorDialog(e);
      }
      finally {
        setIsParsing(false);
      }
    }
  }

  async function handleSelectOfferFile() {
    const dialogOptions = { filters: [{ name: 'Offer Files', extensions: ['offer'] }] } as Electron.OpenDialogOptions;
    const { canceled, filePaths } = await window.remote.dialog.showOpenDialog(dialogOptions);
    if (!canceled && filePaths?.length) {
      handleOpen(filePaths[0]);
    }
  }

  return (
    <Card>
      <Flex justifyContent="space-between">
        <Typography variant="subtitle1"><Trans>Drag & drop an offer file below to view its details</Trans></Typography>
        <Flex flexDirection="row" gap={3}>
          <Button
            variant="outlined"
            color="secondary"
            onClick={handlePasteOfferData}
          >
            <Trans>Paste Offer Data</Trans>
          </Button>
          <Button
            variant="outlined"
            color="primary"
            onClick={handleSelectOfferFile}
          >
            <Trans>Select Offer File</Trans>
          </Button>
        </Flex>
      </Flex>
      <Dropzone maxFiles={1} onDrop={handleDrop} processing={isParsing}>
        <Trans>Drag and drop offer file</Trans>
      </Dropzone>
    </Card>
  );
};

export function OfferImport() {
  return (
    <Grid container>
      <Flex flexDirection="column" flexGrow={1} gap={3}>
        <Flex>
          <Back variant="h5" to="/dashboard/wallets/offers/manage">
            <Trans>View an Offer</Trans>
          </Back>
        </Flex>
        <SelectOfferFile />
      </Flex>
    </Grid>
  );
}