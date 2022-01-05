import React from "react";
import { Trans, t } from '@lingui/macro';
import { useLocalStorage } from '@rehooks/local-storage';
import {
  ButtonLoading,
  CopyToClipboard,
  DialogActions,
  Flex,
  TooltipIcon,
  useOpenDialog,
  useShowError,
} from '@chia/core';
import { OfferTradeRecord } from '@chia/api';
import {
  Button,
  Checkbox,
  Dialog,
  DialogTitle,
  DialogContent,
  Divider,
  FormControlLabel,
  InputAdornment,
  TextField,
  Typography,
} from '@material-ui/core';
import { suggestedFilenameForOffer } from './utils';
import useAssetIdName from '../../../hooks/useAssetIdName';
import useOpenExternal from "../../../hooks/useOpenExternal";
import { IncomingMessage, Shell, Remote } from 'electron';
import OfferLocalStorageKeys from './OfferLocalStorage';
import OfferSummary from './OfferSummary';
import fs from 'fs';

type CommonOfferProps = {
  offerRecord: OfferTradeRecord;
  offerData: string;
};

type CommonDialogProps = {
  open: boolean;
  onClose: (value: boolean) => void;
}

type OfferShareOfferBinDialogProps = CommonOfferProps & CommonDialogProps;
type OfferShareKeybaseDialogProps = CommonOfferProps & CommonDialogProps;

// Posts the offer data to OfferBin and returns a URL to the offer.
async function postToOfferBin(offerData: string, sharePrivately: boolean): Promise<string> {
  return new Promise((resolve, reject) => {
    try {
      const remote: Remote = (window as any).remote;
      const request = remote.net.request({
        method: 'POST',
        protocol: 'https:',
        hostname: 'api.offerbin.io',
        port: 443,
        path: '/upload' + (sharePrivately ? '?private=true' : ''),
      });

      request.setHeader('Content-Type', 'application/text');

      request.on('response', (response: IncomingMessage) => {
        if (response.statusCode === 200) {
          console.log('OfferBin upload completed');

          response.on('error', (e: string) => {
            const error = new Error(`Failed to receive response from OfferBin: ${e}`);
            console.error(error);
            reject(error.message);
          });

          response.on('data', (chunk: Buffer) => {
            try {
              const body = chunk.toString('utf8');
              const { hash } = JSON.parse(body);

              resolve(`https://offerbin.io/offer/${hash}`);
            }
            catch (e) {
              reject(e);
            }
          });
        }
        else {
          const error = new Error(`OfferBin upload failed, statusCode=${response.statusCode}, statusMessage=${response.statusMessage}`);
          console.error(error);
          reject(error.message);
        }
      });

      request.on('error', (error: any) => {
        console.error(error);
        reject(error);
      });

      // Upload and finalize the request
      request.write(offerData);
      request.end();
    }
    catch (error) {
      console.error(error);
      reject(error);
    }
  });
}

function OfferShareOfferBinDialog(props: OfferShareOfferBinDialogProps) {
  const { offerRecord, offerData, onClose, open } = props;
  const openExternal = useOpenExternal();
  const showError = useShowError();
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [sharePrivately, setSharePrivately] = React.useState(false);
  const [sharedURL, setSharedURL] = React.useState('');

  function handleClose() {
    onClose(false);
  }

  async function handleConfirm() {
    try {
      setIsSubmitting(true);

      const url = await postToOfferBin(offerData, sharePrivately);

      console.log(`OfferBin URL (private=${sharePrivately}): ${url}`);
      setSharedURL(url);
    }
    catch (e) {
      showError(e);
    }
    finally {
      setIsSubmitting(false);
    }
  }

  if (sharedURL) {
    return (
      <Dialog
        aria-labelledby="alert-dialog-title"
        aria-describedby="alert-dialog-description"
        maxWidth="xs"
        open={open}
        onClose={handleClose}
        fullWidth
      >
        <DialogTitle>
          <Trans>Offer Shared</Trans>
        </DialogTitle>
        <DialogContent dividers>
          <Flex flexDirection="column" gap={3}>
            <TextField
              label={<Trans>OfferBin URL</Trans>}
              value={sharedURL}
              variant="filled"
              InputProps={{
                readOnly: true,
                endAdornment: (
                  <InputAdornment position="end">
                    <CopyToClipboard value={sharedURL} />
                  </InputAdornment>
                ),
              }}
              fullWidth
            />
            <Flex>
            <Button
              color="secondary"
              variant="contained"
              onClick={() => openExternal(sharedURL)}
            >
              <Trans>View on OfferBin</Trans>
            </Button>
            </Flex>
          </Flex>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={handleClose}
            color="primary"
            variant="contained"
          >
            <Trans>Close</Trans>
          </Button>
        </DialogActions>
      </Dialog>
    );
  }

  return (
    <Dialog
      onClose={handleClose}
      aria-labelledby="alert-dialog-title"
      aria-describedby="alert-dialog-description"
      maxWidth="sm"
      open={open}
      fullWidth
    >
      <DialogTitle id="alert-dialog-title">
        <Trans>Share on OfferBin</Trans>
      </DialogTitle>
      <DialogContent dividers>
        <OfferSummary
          isMyOffer={true}
          summary={offerRecord.summary}
          makerTitle={<Typography variant="subtitle1"><Trans>Your offer:</Trans></Typography>}
          takerTitle={<Typography variant="subtitle1"><Trans>In exchange for:</Trans></Typography>}
          rowIndentation={4}
        />
      </DialogContent>
      <DialogActions>
        <FormControlLabel
          control={<Checkbox name="sharePrivately" checked={sharePrivately} onChange={(event) => setSharePrivately(event.target.checked)} />}
          label={
            <>
              <Trans>Share Privately</Trans>{' '}
              <TooltipIcon>
                <Trans>
                  If selected, your offer will be not be shared publicly.
                </Trans>
              </TooltipIcon>
            </>
          }
        />
        <Flex flexGrow={1}></Flex>
        <Button
          onClick={handleClose}
          color="primary"
          variant="contained"
          disabled={isSubmitting}
        >
          <Trans>Cancel</Trans>
        </Button>
        <ButtonLoading
          onClick={handleConfirm}
          color="secondary"
          variant="contained"
          loading={isSubmitting}
        >
          <Trans>Share</Trans>
        </ButtonLoading>
      </DialogActions>
    </Dialog>
  );
}

OfferShareOfferBinDialog.defaultProps = {
  open: false,
  onClose: () => {},
};

function OfferShareKeybaseDialog(props: OfferShareKeybaseDialogProps) {
  const { offerRecord, offerData, onClose, open } = props;
  const { lookupByAssetId } = useAssetIdName();
  const showError = useShowError();

  function handleClose() {
    onClose(false);
  }

  async function handleKeybaseInstall() {
    try {
      const shell: Shell = (window as any).shell;
      await shell.openExternal('https://keybase.io/download');
    }
    catch (e) {
      showError(new Error(t`Unable to open browser. Install Keybase from https://keybase.io`));
    }
  }

  async function handleKeybaseJoinTeam() {
    try {
      const shell: Shell = (window as any).shell;
      await shell.openExternal('keybase://team-page/chia_offers/join');
    }
    catch (e) {
      showError(new Error(t`Unable to open Keybase. Install Keybase from https://keybase.io`));
    }
  }

  async function handleKeybaseGoToChannel() {
    try {
      const shell: Shell = (window as any).shell;
      await shell.openExternal('keybase://chat/chia_offers#offers-trading');
    }
    catch (e) {
      showError(new Error(t`Unable to open Keybase. Install Keybase from https://keybase.io`));
    }
  }

  async function handleSaveOffer() {
    const dialogOptions = {
      defaultPath: suggestedFilenameForOffer(offerRecord.summary, lookupByAssetId),
    }
    const remote: Remote = (window as any).remote;
    const result = await remote.dialog.showSaveDialog(dialogOptions);
    const { filePath, canceled } = result;

    if (!canceled && filePath) {
      try {
        fs.writeFileSync(filePath, offerData);
      }
      catch (err) {
        console.error(err);
      }
    }
  }

  return (
    <Dialog
      onClose={handleClose}
      aria-labelledby="alert-dialog-title"
      aria-describedby="alert-dialog-description"
      maxWidth="sm"
      open={open}
      fullWidth
    >
      <DialogTitle id="alert-dialog-title">
        <Trans>Share on Keybase</Trans>
      </DialogTitle>
      <DialogContent dividers>
        <Flex flexDirection="column" gap={2}>
          <Typography variant="body2">
            <Trans>
              Keybase is a secure messaging and file sharing application. To share an offer
              in the Keybase chia_offers team, you must first have Keybase installed.
            </Trans>
          </Typography>
          <Flex justifyContent="center" flexGrow={0} >
            <Button
              onClick={handleKeybaseInstall}
              color="secondary"
              variant="contained"
            >
              <Trans>Install Keybase</Trans>
            </Button>
          </Flex>
          <Divider />
          <Typography variant="body2">
            <Trans>
              Before posting an offer in Keybase to the #offers-trading channel, you must
              first join the chia_offers team.
            </Trans>
          </Typography>
          <Flex justifyContent="center" flexGrow={0}>
            <Button
              onClick={handleKeybaseJoinTeam}
              color="secondary"
              variant="contained"
            >
              <Trans>Join chia_offers</Trans>
            </Button>
          </Flex>
          <Divider />
          <Typography variant="body2">
            <Trans>
              If you have already joined the chia_offers team, you can post your offer file to the
              #offers-trading channel. When sharing an offer file, be sure to include a description
              of which assets are being offered and requested.
            </Trans>
          </Typography>
          <Flex justifyContent="center" flexGrow={0}>
            <Button
              onClick={handleKeybaseGoToChannel}
              color="primary"
              variant="contained"
            >
              <Trans>Go to #offers-trading</Trans>
            </Button>
          </Flex>
        </Flex>
      </DialogContent>
      <DialogActions>
        <Button
          onClick={handleSaveOffer}
          color="secondary"
          variant="contained"
        >
          <Trans>Save Offer File</Trans>
        </Button>
        <Button
          onClick={handleClose}
          color="primary"
          variant="contained"
        >
          <Trans>Close</Trans>
        </Button>
      </DialogActions>
    </Dialog>
  );
}

OfferShareKeybaseDialog.defaultProps = {
  open: false,
  onClose: () => {},
};

type OfferShareDialogProps = CommonOfferProps & CommonDialogProps & {
  showSuppressionCheckbox: boolean;
};

export default function OfferShareDialog(props: OfferShareDialogProps) {
  const { offerRecord, offerData, showSuppressionCheckbox, onClose, open } = props;
  const openDialog = useOpenDialog();
  const [suppressShareOnCreate, setSuppressShareOnCreate] = useLocalStorage<boolean>(OfferLocalStorageKeys.SUPPRESS_SHARE_ON_CREATE);

  function handleClose() {
    onClose(false);
  }

  async function handleOfferBin() {
    await openDialog(
      <OfferShareOfferBinDialog offerRecord={offerRecord} offerData={offerData} />
    );
  }

  async function handleKeybase() {
    await openDialog(
      <OfferShareKeybaseDialog offerRecord={offerRecord} offerData={offerData} />
    );
  }

  function toggleSuppression(value: boolean) {
    setSuppressShareOnCreate(value);
  }

  return (
    <Dialog
      onClose={handleClose}
      aria-labelledby="alert-dialog-title"
      aria-describedby="alert-dialog-description"
      maxWidth="md"
      open={open}
    >
      <DialogTitle id="alert-dialog-title">
        <Trans>Share Offer</Trans>
      </DialogTitle>

      <DialogContent dividers>
        <Flex flexDirection="column" gap={2}>
          <Flex flexDirection="column" gap={2}>
            <Typography variant="subtitle1">Where would you like to share your offer?</Typography>
            <Flex flexDirection="row" gap={3}>
              <Button variant="contained" color="default" onClick={handleOfferBin}>
                OfferBin
              </Button>
              <Button
                variant="contained"
                color="secondary"
                onClick={handleKeybase}
              >
                <Flex flexDirection="column">
                  Keybase
                </Flex>
              </Button>
              <Button variant="contained" color="secondary" disabled={true}>
                <Flex flexDirection="column">
                  Reddit
                  <Typography variant="caption"><Trans>(Coming Soon)</Trans></Typography>
                </Flex>
              </Button>
            </Flex>
          </Flex>
          {showSuppressionCheckbox && (
            <>
              <FormControlLabel
                control={<Checkbox name="cancelWithTransaction" checked={!!suppressShareOnCreate} onChange={(event) => toggleSuppression(event.target.checked)} />}
                label={<Trans>Do not show this dialog again</Trans>}
              />
            </>
          )}
        </Flex>
      </DialogContent>
      <DialogActions>
        <Button
          onClick={handleClose}
          color="primary"
          variant="contained"
        >
          <Trans>Close</Trans>
        </Button>
      </DialogActions>
    </Dialog>
  );
}

OfferShareDialog.defaultProps = {
  open: false,
  onClose: () => {},
  showSuppressionCheckbox: false,
};
