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
  useOpenExternal,
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
import { shortSummaryForOffer, suggestedFilenameForOffer } from './utils';
import useAssetIdName, { AssetIdMapEntry } from '../../hooks/useAssetIdName';
import { IncomingMessage, Shell, Remote } from 'electron';
import OfferLocalStorageKeys from './OfferLocalStorage';
import OfferSummary from './OfferSummary';
import child_process from 'child_process';
import fs from 'fs';
import path from 'path';

type CommonOfferProps = {
  offerRecord: OfferTradeRecord;
  offerData: string;
};

type CommonDialogProps = {
  open: boolean;
  onClose: (value: boolean) => void;
}

type OfferShareOfferBinDialogProps = CommonOfferProps & CommonDialogProps;
type OfferShareHashgreenDialogProps = CommonOfferProps & CommonDialogProps;
type OfferShareKeybaseDialogProps = CommonOfferProps & CommonDialogProps;

async function writeTempOfferFile(offerData: string, filename: string): Promise<string> {
  const ipcRenderer = (window as any).ipcRenderer;
  const tempRoot = await ipcRenderer?.invoke('getTempDir');
  const tempPath = fs.mkdtempSync(path.join(tempRoot, 'offer'));
  const filePath = path.join(tempPath, filename);

  fs.writeFileSync(filePath, offerData);

  return filePath;
}

// Posts the offer data to OfferBin and returns a URL to the offer.
async function postToOfferBin(offerData: string, sharePrivately: boolean): Promise<string> {
  const ipcRenderer = (window as any).ipcRenderer;
  const requestOptions = {
    method: 'POST',
    protocol: 'https:',
    hostname: 'api.offerbin.io',
    port: 443,
    path: '/upload' + (sharePrivately ? '?private=true' : ''),
  };
  const requestHeaders = {
    'Content-Type': 'application/text',
  }
  const requestData = offerData;
  const { err, statusCode, statusMessage, responseBody } = await ipcRenderer?.invoke('fetchTextResponse', requestOptions, requestHeaders, requestData);

  if (err || statusCode !== 200) {
    const error = new Error(`OfferBin upload failed: ${err}, statusCode=${statusCode}, statusMessage=${statusMessage}, response=${responseBody}`);
    throw error;
  }

  console.log('OfferBin upload completed');
  const { hash } = JSON.parse(responseBody);

  return `https://offerbin.io/offer/${hash}`;
}

enum HashgreenErrorCodes {
  OFFERED_AMOUNT_TOO_SMALL = 40020, // The offered amount is too small
  MARKET_NOT_FOUND = 50029, // Pairing doesn't exist e.g. XCH/RandoCoin
  OFFER_FILE_EXISTS = 50037, // Offer already shared
  COINS_ALREADY_COMMITTED = 50041, // Coins in the offer are already committed in another offer
};

async function postToHashgreen(offerData: string): Promise<string> {
  const ipcRenderer = (window as any).ipcRenderer;
  const requestOptions = {
    method: 'POST',
    protocol: 'https:',
    hostname: 'hash.green',
    port: 443,
    path: '/api/v1/orders',
  };
  const requestHeaders = {
    'accept': 'application/json',
    'Content-Type': 'application/x-www-form-urlencoded',
  }
  const requestData = `offer=${offerData}`;
  const { err, statusCode, statusMessage, responseBody } = await ipcRenderer?.invoke('fetchTextResponse', requestOptions, requestHeaders, requestData);

  if (err) {
    const error = new Error(`Failed to post offer to hash.green: ${err}, statusCode=${statusCode}, statusMessage=${statusMessage}`);
    throw error;
  }

  if (statusCode === 200) {
    console.log('Hashgreen upload completed');
    const jsonObj = JSON.parse(responseBody);
    const { data } = jsonObj;
    const id = data?.id;

    if (id) {
      return `https://hash.green/dex?order=${id}`;
    }
    else {
      const error = new Error(`Hashgreen response missing data.id: ${responseBody}`);
      throw error;
    }
  }
  else {
    const jsonObj = JSON.parse(responseBody);
    const { code, msg, data } = jsonObj;

    if (code === HashgreenErrorCodes.OFFER_FILE_EXISTS && data) {
      return `https://hash.green/dex?order=${data}`;
    }
    else {
      console.log(`Upload failure response: ${responseBody}`);
      switch (code) {
        case HashgreenErrorCodes.MARKET_NOT_FOUND:
          throw new Error(`Hashgreen upload rejected. Pairing is not supported: ${msg}`);
        case HashgreenErrorCodes.COINS_ALREADY_COMMITTED:
          throw new Error(`Hashgreen upload rejected. Offer contains coins that are in use by another offer: ${msg}`);
        case HashgreenErrorCodes.OFFERED_AMOUNT_TOO_SMALL:
          throw new Error(`Hashgreen upload rejected. Offer amount is too small: ${msg}`);
        default:
          throw new Error(`Hashgreen upload rejected: code=${code} msg=${msg} data=${data}`);
      }
    }
  }
}

enum KeybaseCLIActions {
  JOIN_TEAM = 'JOIN_TEAM',
  JOIN_CHANNEL = 'JOIN_CHANNEL',
  UPLOAD_OFFER = 'UPLOAD_OFFER',
  CHECK_TEAM_MEMBERSHIP = 'CHECK_TEAM_MEMBERSHIP',
};

type KeybaseCLIRequest = {
  action: KeybaseCLIActions,
  uploadArgs?: {
    title: string,
    filePath: string,
  }
};

const KeybaseTeamName = 'chia_offers';
const KeybaseChannelName = 'offers-trading';

async function execKeybaseCLI(request: KeybaseCLIRequest): Promise<boolean> {
  return new Promise((resolve, reject) => {
    try {
      const options: any = {};

      if (process.platform === 'darwin') {
        const env = Object.assign({}, process.env);

        // Add /usr/local/bin and a direct path to the keybase binary on macOS.
        // Without these additions, the keybase binary may not be found.
        env.PATH = `${env.PATH}:/usr/local/bin:/Applications/Keybase.app/Contents/SharedSupport/bin`;

        options['env'] = env;
      }

      let command: string | undefined = undefined;

      switch (request.action) {
        case KeybaseCLIActions.JOIN_TEAM:
          command = `keybase team request-access ${KeybaseTeamName}`;
          break;
        case KeybaseCLIActions.JOIN_CHANNEL:
          command = `keybase chat join-channel ${KeybaseTeamName} '#${KeybaseChannelName}'`;
          break;
        case KeybaseCLIActions.UPLOAD_OFFER:
          const { title, filePath } = request.uploadArgs!;
          if (title && filePath) {
            command = `keybase chat upload "${KeybaseTeamName}" --channel "${KeybaseChannelName}" --title "${title}" "${filePath}"`;
          }
          else {
            reject(new Error(`Missing title or filePath in request.uploadArgs`));
          }
          break;
        case KeybaseCLIActions.CHECK_TEAM_MEMBERSHIP:
          command = 'keybase team list-memberships';
          break;
        default:
          reject(new Error(`Unknown KeybaseCLI action: ${request.action}`));
          break;
      }

      if (command) {
        child_process.exec(
          command,
          options,
          (error, stdout, stderr) => {
            if (error) {
              console.error(`Keybase error: ${error}`);
              switch (request.action) {
                case KeybaseCLIActions.CHECK_TEAM_MEMBERSHIP:
                  resolve(stdout.indexOf(`${KeybaseTeamName}`) === 0);
                  break;
                case KeybaseCLIActions.JOIN_TEAM:
                  resolve(stderr.indexOf('(code 2665)') !== -1);
                  break;
                default:
                  if (stderr.indexOf('(code 2623)') !== -1) {
                    resolve(false);
                  }
                  else {
                    reject(new Error(t`Failed to execute Keybase command: ${stderr}`));
                  }
              }
            }

            resolve(true);
        });
      }
      else {
        reject(new Error(`Missing command for action: ${request.action}`));
      }
    }
    catch (error) {
      console.error(error);
      reject(error);
    }
  });
}

async function postToKeybase(
  offerRecord: OfferTradeRecord,
  offerData: string,
  lookupByAssetId: (assetId: string) => AssetIdMapEntry | undefined): Promise<boolean> {

  const filename = suggestedFilenameForOffer(offerRecord.summary, lookupByAssetId);
  const summary = shortSummaryForOffer(offerRecord.summary, lookupByAssetId);

  let filePath = '';
  let success = false;

  filePath = await writeTempOfferFile(offerData, filename);

  try {
    success = await execKeybaseCLI({ action: KeybaseCLIActions.UPLOAD_OFFER, uploadArgs: { title: summary, filePath } });
  }
  finally {
    if (filePath) {
      fs.unlinkSync(filePath);
    }
  }
  return success;
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

function OfferShareHashgreenDialog(props: OfferShareHashgreenDialogProps) {
  const { offerRecord, offerData, onClose, open } = props;
  const openExternal = useOpenExternal();
  const showError = useShowError();
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [sharedURL, setSharedURL] = React.useState('');

  function handleClose() {
    onClose(false);
  }

  async function handleConfirm() {
    try {
      setIsSubmitting(true);

      const url = await postToHashgreen(offerData);

      console.log(`Hashgreen URL: ${url}`);
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
              label={<Trans>Hashgreen DEX URL</Trans>}
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
              <Trans>View on Hashgreen DEX</Trans>
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
        <Trans>Share on Hashgreen DEX</Trans>
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

OfferShareHashgreenDialog.defaultProps = {
  open: false,
  onClose: () => {},
};

function OfferShareKeybaseDialog(props: OfferShareKeybaseDialogProps) {
  const { offerRecord, offerData, onClose, open } = props;
  const { lookupByAssetId } = useAssetIdName();
  const showError = useShowError();
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [isJoiningTeam, setIsJoiningTeam] = React.useState(false);
  const [shared, setShared] = React.useState(false);

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
    setIsJoiningTeam(true);

    try {
      const shell: Shell = (window as any).shell;
      const joinTeamSucceeded = await execKeybaseCLI({ action: KeybaseCLIActions.JOIN_TEAM });
      let joinTeamThroughURL = false;
      if (joinTeamSucceeded) {
        let attempts = 0;
        let isMember = false;
        while (attempts < 20) {
          await new Promise(resolve => setTimeout(resolve, 1000));
          isMember = await execKeybaseCLI({ action: KeybaseCLIActions.CHECK_TEAM_MEMBERSHIP });

          if (isMember) {
            console.log("Joined team successfully");
            break;
          }

          attempts++;
        }

        if (isMember) {
          attempts = 0;
          let joinChannelSucceeded = false;
          while (attempts < 30) {
            await new Promise(resolve => setTimeout(resolve, 1000));
            joinChannelSucceeded = await execKeybaseCLI({ action: KeybaseCLIActions.JOIN_CHANNEL });

            if (joinChannelSucceeded) {
              break;
            }

            attempts++;
          }

          if (joinChannelSucceeded) {
            console.log("Joined channel successfully");
            await new Promise(resolve => setTimeout(resolve, 1000));
            await shell.openExternal(`keybase://chat/${KeybaseTeamName}#${KeybaseChannelName}`);
          }
          else {
            console.error("Failed to join channel");
            shell.openExternal(`keybase://chat/${KeybaseTeamName}#${KeybaseChannelName}`);
          }
        }
        else {
          console.error("Failed to join team");
          joinTeamThroughURL = true;
        }
      }
      else {
        joinTeamThroughURL = true;
      }

      if (joinTeamThroughURL) {
        await shell.openExternal(`keybase://team-page/${KeybaseTeamName}/join`);
      }
    }
    catch (e) {
      showError(new Error(t`Keybase command failed ${e}. If you haven't installed Keybase, you can download from https://keybase.io`));
    }
    finally {
      setIsJoiningTeam(false);
    }
  }

  async function handleKeybaseGoToChannel() {
    try {
      const shell: Shell = (window as any).shell;
      await shell.openExternal(`keybase://chat/${KeybaseTeamName}#${KeybaseChannelName}`);
    }
    catch (e) {
      showError(new Error(t`Unable to open Keybase. Install Keybase from https://keybase.io`));
    }
  }

  async function handleKeybaseShare() {
    let success = false;

    try {
      setIsSubmitting(true);
      success = await postToKeybase(offerRecord, offerData, lookupByAssetId);

      if (success) {
        setShared(true);
      }
    }
    catch (e) {
      showError(e);
    }
    finally {
      setIsSubmitting(false);
    }
  }

  if (shared) {
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
            <Trans>Your offer has been successfully posted to Keybase.</Trans>
          </Flex>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={handleKeybaseGoToChannel}
            color="secondary"
            variant="contained"
          >
            <Trans>Go to #{KeybaseChannelName}</Trans>
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
              in the Keybase {KeybaseTeamName} team, you must first have Keybase installed.
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
              Before posting an offer in Keybase to the #{KeybaseChannelName} channel, you must
              first join the {KeybaseTeamName} team. Please note that it might take a few moments
              to join the channel.
            </Trans>
          </Typography>
          <Flex justifyContent="center" flexGrow={0}>
            <ButtonLoading
              onClick={handleKeybaseJoinTeam}
              color="secondary"
              variant="contained"
              loading={isJoiningTeam}
            >
              <Trans>Join {KeybaseTeamName}</Trans>
            </ButtonLoading>
          </Flex>
        </Flex>
      </DialogContent>
      <DialogActions>
        <Button
          onClick={handleKeybaseGoToChannel}
          color="primary"
          variant="contained"
        >
          <Trans>Go to #{KeybaseChannelName}</Trans>
        </Button>
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
          onClick={handleKeybaseShare}
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

  async function handleHashgreen() {
    await openDialog(
      <OfferShareHashgreenDialog offerRecord={offerRecord} offerData={offerData} />
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
              <Button
                variant="contained"
                color="default"
                onClick={handleOfferBin}
              >
                OfferBin
              </Button>
              <Button
                variant="contained"
                color="default"
                onClick={handleHashgreen}
              >
                Hashgreen DEX
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
