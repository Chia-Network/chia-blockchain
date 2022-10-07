import React, { useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { Trans, t } from '@lingui/macro';
import moment from 'moment';
import BigNumber from 'bignumber.js';
import { Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import {
  Button,
  ButtonLoading,
  Card,
  CardHero,
  Fee,
  Flex,
  Form,
  IconButton,
  LoadingOverlay,
  More,
  TableControlled,
  TooltipIcon,
  useOpenDialog,
  chiaToMojo,
  useCurrencyCode,
  useSerializedNavigationState,
  useShowSaveDialog,
  Tooltip,
  LayoutDashboardSub,
  MenuItem,
} from '@chia/core';
import { OfferSummaryRecord, OfferTradeRecord } from '@chia/api';
import {
  Box,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  FormControlLabel,
  Grid,
  ListItemIcon,
  Typography,
} from '@mui/material';
import {
  Cancel,
  GetApp as Download,
  Info,
  Reply as Share,
  Visibility,
} from '@mui/icons-material';
import {
  useCancelOfferMutation,
  useGetOfferDataMutation,
  useGetWalletsQuery,
} from '@chia/api-react';
import {
  colorForOfferState,
  displayStringForOfferState,
  formatAmountForWalletType,
  offerAssetTypeForAssetId,
  offerContainsAssetOfType,
} from './utils';
import { launcherIdToNFTId } from '../../util/nfts';
import useAssetIdName from '../../hooks/useAssetIdName';
import useSaveOfferFile from '../../hooks/useSaveOfferFile';
import useWalletOffers from '../../hooks/useWalletOffers';
import { CreateOfferEditor } from './OfferEditor';
import { CreateNFTOfferEditor } from './NFTOfferEditor';
import { OfferImport } from './OfferImport';
import NFTOfferViewer from './NFTOfferViewer';
import OfferAsset from './OfferAsset';
import OfferDataDialog from './OfferDataDialog';
import OfferShareDialog from './OfferShareDialog';
import OfferState from './OfferState';
import CreateOfferBuilder from '../offers2/CreateOfferBuilder';
import OfferBuilderImport from '../offers2/OfferBuilderImport';
import OfferBuilderViewer from '../offers2/OfferBuilderViewer';

type ConfirmOfferCancellationProps = {
  canCancelWithTransaction: boolean;
  onClose: (value: any) => void;
  open: boolean;
};

function ConfirmOfferCancellation(props: ConfirmOfferCancellationProps) {
  const { canCancelWithTransaction, onClose, open } = props;
  const methods = useForm({
    defaultValues: {
      fee: '',
    },
  });
  const [cancelWithTransaction, setCancelWithTransaction] = useState<boolean>(
    canCancelWithTransaction,
  );

  function handleCancel() {
    onClose([false]);
  }

  async function handleConfirm() {
    const { fee: xchFee } = methods.getValues();

    const fee = cancelWithTransaction ? chiaToMojo(xchFee) : new BigNumber(0);

    onClose([true, { cancelWithTransaction, cancellationFee: fee }]);
  }

  return (
    <Dialog
      onClose={handleCancel}
      open={open}
      aria-labelledby="alert-dialog-title"
      aria-describedby="alert-dialog-description"
    >
      <DialogTitle id="alert-dialog-title">
        <Trans>Cancel Offer</Trans>
      </DialogTitle>
      <DialogContent>
        <DialogContentText id="alert-dialog-description">
          <Form methods={methods} onSubmit={handleConfirm}>
            <Flex flexDirection="column" gap={3}>
              <Typography variant="body1">
                <Trans>Are you sure you want to cancel your offer?</Trans>
              </Typography>
              {canCancelWithTransaction && (
                <>
                  <Typography variant="body1">
                    <Trans>
                      If you have already shared your offer file, you may need
                      to submit a transaction to cancel the pending offer. Click
                      "Cancel on blockchain" to submit a cancellation
                      transaction.
                    </Trans>
                  </Typography>
                  <Flex flexDirection="row" gap={3}>
                    <Grid container>
                      <Grid xs={6} item>
                        <FormControlLabel
                          control={
                            <Checkbox
                              name="cancelWithTransaction"
                              checked={cancelWithTransaction}
                              onChange={(event) =>
                                setCancelWithTransaction(event.target.checked)
                              }
                            />
                          }
                          label={
                            <>
                              <Trans>Cancel on blockchain</Trans>{' '}
                              <TooltipIcon>
                                <Trans>
                                  Creates and submits a transaction on the
                                  blockchain that cancels the offer
                                </Trans>
                              </TooltipIcon>
                            </>
                          }
                        />
                      </Grid>
                      {cancelWithTransaction && (
                        <Grid xs={6} item>
                          <Fee
                            id="filled-secondary"
                            variant="filled"
                            name="fee"
                            color="secondary"
                            label={<Trans>Fee</Trans>}
                            fullWidth
                          />
                        </Grid>
                      )}
                    </Grid>
                  </Flex>
                </>
              )}
            </Flex>
          </Form>
        </DialogContentText>
      </DialogContent>
      <DialogActions>
        <Flex
          flexDirection="row"
          gap={3}
          style={{ paddingBottom: '8px', paddingRight: '16px' }}
        >
          <Button
            onClick={handleCancel}
            color="secondary"
            variant="outlined"
            autoFocus
          >
            <Trans>Close</Trans>
          </Button>
          <ButtonLoading
            onClick={handleConfirm}
            color="danger"
            variant="contained"
          >
            <Trans>Cancel Offer</Trans>
          </ButtonLoading>
        </Flex>
      </DialogActions>
    </Dialog>
  );
}

ConfirmOfferCancellation.defaultProps = {
  canCancelWithTransaction: true,
  onClose: () => {},
  open: true,
};

function resolveOfferInfo(
  summary: OfferSummaryRecord,
  summaryKey: string,
  lookupByAssetId: (assetId: string) => AssetIdMapEntry | undefined,
) {
  const resolvedOfferInfo = Object.entries(summary[summaryKey]).map(
    ([assetId, amount]) => {
      const assetType = offerAssetTypeForAssetId(assetId, summary);
      const assetIdInfo =
        assetType === OfferAsset.NFT ? undefined : lookupByAssetId(assetId);
      const displayAmount = assetIdInfo
        ? formatAmountForWalletType(amount as number, assetIdInfo.walletType)
        : amount;
      let displayName = '';
      if (assetType === OfferAsset.NFT) {
        displayName = launcherIdToNFTId(assetId);
      } else {
        displayName = assetIdInfo?.displayName ?? t`Unknown CAT`;
      }
      return {
        displayAmount,
        displayName,
      };
    },
  );
  return resolvedOfferInfo;
}

type OfferListProps = {
  title: string | React.ReactElement;
  includeMyOffers: boolean;
  includeTakenOffers: boolean;
};

function OfferList(props: OfferListProps) {
  const { title, includeMyOffers, includeTakenOffers } = props;
  const showSaveDialog = useShowSaveDialog();
  const [getOfferData] = useGetOfferDataMutation();
  const [cancelOffer] = useCancelOfferMutation();
  const [saveOffer] = useSaveOfferFile();
  const { data: wallets, isLoading: isLoadingWallets } = useGetWalletsQuery();
  const { lookupByAssetId } = useAssetIdName();
  const testnet = useCurrencyCode() === 'TXCH';
  const openDialog = useOpenDialog();
  const { navigate } = useSerializedNavigationState();
  const {
    offers,
    isLoading: isWalletOffersLoading,
    page,
    rowsPerPage,
    count,
    pageChange,
  } = useWalletOffers(
    5,
    0,
    includeMyOffers,
    includeTakenOffers,
    'RELEVANCE',
    false,
  );

  async function handleShowOfferData(offerData: string) {
    openDialog(<OfferDataDialog offerData={offerData} />);
  }

  async function handleCancelOffer(
    tradeId: string,
    canCancelWithTransaction: boolean,
  ) {
    const [cancelConfirmed, cancellationOptions] = await openDialog(
      <ConfirmOfferCancellation
        canCancelWithTransaction={canCancelWithTransaction}
      />,
    );

    if (cancelConfirmed === true) {
      const secure = canCancelWithTransaction
        ? cancellationOptions.cancelWithTransaction
        : false;
      const fee = canCancelWithTransaction
        ? cancellationOptions.cancellationFee
        : 0;
      await cancelOffer({ tradeId, secure: secure, fee: fee });
    }
  }

  function handleRowClick(event: any, row: OfferTradeRecord) {
    navigate('/dashboard/offers/view', {
      state: {
        referrerPath: '/dashboard/offers',
        offerSummary: row.summary,
        isMyOffer: row.isMyOffer,
        state: row.status,
      },
    });
  }

  async function handleShare(event: any, row: OfferTradeRecord) {
    await openDialog(
      <OfferShareDialog
        offerRecord={row}
        offerData={row._offerData}
        exportOffer={() => saveOffer(row.tradeId)}
        testnet={testnet}
      />,
    );
  }

  const cols = useMemo(() => {
    return [
      {
        field: (row: OfferTradeRecord) => {
          const { status } = row;

          return (
            <Box onClick={(event) => handleRowClick(event, row)}>
              <Chip
                label={displayStringForOfferState(status)}
                variant="outlined"
                color={colorForOfferState(status)}
              />
            </Box>
          );
        },
        minWidth: '170px',
        maxWidth: '170px',
        title: <Trans>Status</Trans>,
      },
      {
        field: (row: OfferTradeRecord) => {
          const resolvedOfferInfo = resolveOfferInfo(
            row.summary,
            'offered',
            lookupByAssetId,
          );
          return resolvedOfferInfo.map((info, index) => (
            <Flex
              flexDirection="row"
              gap={0.5}
              key={`${index}-${info.displayName}`}
            >
              <Typography variant="body2">
                {(info.displayAmount as any).toString()}
              </Typography>
              <Typography noWrap variant="body2">
                {info.displayName}
              </Typography>
            </Flex>
          ));
        },
        minWidth: '160px',
        title: <Trans>Offered</Trans>,
      },
      {
        field: (row: OfferTradeRecord) => {
          const resolvedOfferInfo = resolveOfferInfo(
            row.summary,
            'requested',
            lookupByAssetId,
          );
          return resolvedOfferInfo.map((info, index) => (
            <Flex
              flexDirection="row"
              gap={0.5}
              key={`${index}-${info.displayName}`}
            >
              <Typography variant="body2">
                {(info.displayAmount as any).toString()}
              </Typography>
              <Typography noWrap variant="body2">
                {info.displayName}
              </Typography>
            </Flex>
          ));
        },
        minWidth: '160px',
        title: <Trans>Requested</Trans>,
      },
      {
        field: (row: OfferTradeRecord) => {
          const { createdAtTime } = row;

          return (
            <Box onClick={(event) => handleRowClick(event, row)}>
              <Typography color="textSecondary" variant="body2">
                {moment(createdAtTime * 1000).format('LLL')}
              </Typography>
            </Box>
          );
        },
        minWidth: '220px',
        maxWidth: '220px',
        title: <Trans>Creation Date</Trans>,
      },
      {
        field: (row: OfferTradeRecord) => {
          const { tradeId, status } = row;
          const canExport = status === OfferState.PENDING_ACCEPT; // implies isMyOffer === true
          const canDisplayData = status === OfferState.PENDING_ACCEPT;
          const canCancel =
            status === OfferState.PENDING_ACCEPT ||
            status === OfferState.PENDING_CONFIRM;
          const canShare = status === OfferState.PENDING_ACCEPT;
          const canCancelWithTransaction =
            canCancel && status === OfferState.PENDING_ACCEPT;

          return (
            <Flex flexDirection="row" justifyContent="center" gap={0}>
              <Flex style={{ width: '32px' }}>
                {canShare && (
                  <Tooltip title={<Trans>Share</Trans>}>
                    <IconButton
                      size="small"
                      disabled={!canShare}
                      onClick={() => handleShare(undefined, row)}
                    >
                      <Share style={{ transform: 'scaleX(-1)' }} />
                    </IconButton>
                  </Tooltip>
                )}
              </Flex>
              <Flex style={{ width: '32px' }}>
                <More>
                  <MenuItem
                    onClick={() => handleRowClick(undefined, row)}
                    close
                  >
                    <ListItemIcon>
                      <Info fontSize="small" />
                    </ListItemIcon>
                    <Typography variant="inherit" noWrap>
                      <Trans>Show Details</Trans>
                    </Typography>
                  </MenuItem>
                  {canDisplayData && (
                    <MenuItem
                      onClick={() => handleShowOfferData(row._offerData)}
                      close
                    >
                      <ListItemIcon>
                        <Visibility fontSize="small" />
                      </ListItemIcon>
                      <Typography variant="inherit" noWrap>
                        <Trans>Display Offer Data</Trans>
                      </Typography>
                    </MenuItem>
                  )}
                  {canExport && (
                    <MenuItem onClick={() => saveOffer(tradeId)} close>
                      <ListItemIcon>
                        <Download fontSize="small" />
                      </ListItemIcon>
                      <Typography variant="inherit" noWrap>
                        <Trans>Save Offer File</Trans>
                      </Typography>
                    </MenuItem>
                  )}
                  {canCancel && (
                    <MenuItem
                      onClick={() =>
                        handleCancelOffer(tradeId, canCancelWithTransaction)
                      }
                      close
                    >
                      <ListItemIcon>
                        <Cancel fontSize="small" />
                      </ListItemIcon>
                      <Typography variant="inherit" noWrap>
                        <Trans>Cancel Offer</Trans>
                      </Typography>
                    </MenuItem>
                  )}
                </More>
              </Flex>
            </Flex>
          );
        },
        minWidth: '100px',
        maxWidth: '100px',
        title: <Flex justifyContent="center">Actions</Flex>,
      },
    ];
  }, []);

  const hasOffers = !!offers?.length;

  return (
    <Card title={title} titleVariant="h6" transparent>
      <LoadingOverlay loading={isWalletOffersLoading || isLoadingWallets}>
        <TableControlled
          rows={offers}
          cols={cols}
          rowsPerPageOptions={[5, 25, 100]}
          count={count}
          rowsPerPage={rowsPerPage}
          pages={hasOffers}
          page={page}
          onPageChange={pageChange}
          isLoading={isWalletOffersLoading}
          caption={
            !hasOffers &&
            !isWalletOffersLoading &&
            !isLoadingWallets && (
              <Typography variant="body2" align="center">
                <Trans>No current offers</Trans>
              </Typography>
            )
          }
        />
      </LoadingOverlay>
    </Card>
  );
}

export function OfferManager() {
  const navigate = useNavigate();

  function handleOfferBuilder() {
    navigate('/dashboard/offers/builder', {
      state: { referrerPath: '/dashboard/offers' },
    });
  }

  return (
    <Flex flexDirection="column" gap={4} alignItems="stretch">
      <Flex gap={4} flexDirection="column">
        <Flex flexDirection="column" gap={1}>
          <Typography variant="h5">
            <Trans>Offer Management</Trans>
          </Typography>
          <Typography variant="body2" color="textSecondary">
            <Trans>
              Offers are a way to trade assets in a genuinely peer-to-peer way
              to eliminate counterparty risk.
            </Trans>
          </Typography>
        </Flex>
        <Box>
          <Grid spacing={4} container>
            <Grid xs={12} md={6} item>
              <Flex flexDirection="column" gap={2} height="100%">
                <Typography variant="h6">
                  <Trans>Create Offer</Trans>
                </Typography>
                <CardHero variant="outlined" fullHeight>
                  <Flex flexDirection="column" gap={4} height="100%">
                    <Flex flexDirection="column" gap={2} flexGrow={1}>
                      <Typography variant="h6">
                        <Trans>Offer Builder</Trans>
                      </Typography>
                      <Typography variant="body1" color="textSecondary">
                        <Trans>
                          Create a file that you can use to trade XCH, Chia
                          Asset Tokens, or NFTs with no counter-party risk.
                        </Trans>
                      </Typography>
                    </Flex>
                    <Flex justifyContent="flex-end">
                      <Button
                        onClick={handleOfferBuilder}
                        variant="contained"
                        color="primary"
                      >
                        <Typography variant="inherit" noWrap>
                          <Trans>Create an Offer</Trans>
                        </Typography>
                      </Button>
                    </Flex>
                  </Flex>
                </CardHero>
              </Flex>
            </Grid>
            <Grid xs={12} md={6} item>
              <Flex flexDirection="column" gap={2} height="100%">
                <Typography variant="h6">
                  <Trans>View Offer</Trans>
                </Typography>
                <OfferBuilderImport />
              </Flex>
            </Grid>
          </Grid>
        </Box>
      </Flex>
      <OfferList
        title={<Trans>Offers you created</Trans>}
        includeMyOffers={true}
        includeTakenOffers={false}
      />
      <OfferList
        title={<Trans>Offers you accepted</Trans>}
        includeMyOffers={false}
        includeTakenOffers={true}
      />
    </Flex>
  );
}

export function CreateOffer() {
  const { getLocationState } = useSerializedNavigationState();
  const locationState = getLocationState(); // For cases where we know that the state has been serialized
  const openDialog = useOpenDialog();
  const [saveOffer] = useSaveOfferFile();
  const testnet = useCurrencyCode() === 'TXCH';

  async function handleOfferCreated(obj: { offerRecord: any; offerData: any }) {
    const { offerRecord, offerData } = obj;

    await openDialog(
      <OfferShareDialog
        offerRecord={offerRecord}
        offerData={offerData as string}
        showSuppressionCheckbox={true}
        exportOffer={() => saveOffer(offerRecord.tradeId)}
        testnet={testnet}
      />,
    );
  }

  return (
    <LayoutDashboardSub>
      <Routes>
        <Route
          path="builder"
          element={
            <CreateOfferBuilder
              nftId={locationState?.nftId}
              referrerPath={locationState?.referrerPath}
              onOfferCreated={handleOfferCreated}
            />
          }
        />
        <Route
          path="create"
          element={
            <CreateOfferEditor
              walletId={locationState?.walletId}
              walletType={locationState?.walletType}
              referrerPath={locationState?.referrerPath}
              onOfferCreated={handleOfferCreated}
            />
          }
        />
        <Route
          path="create-with-nft"
          element={
            <CreateNFTOfferEditor
              nft={locationState?.nft}
              exchangeType={locationState?.exchangeType}
              referrerPath={locationState?.referrerPath}
              onOfferCreated={handleOfferCreated}
            />
          }
        />
        <Route path="import" element={<OfferImport />} />

        <Route
          path="view-nft"
          element={
            <NFTOfferViewer
              tradeRecord={locationState?.tradeRecord}
              offerData={locationState?.offerData}
              offerSummary={locationState?.offerSummary}
              offerFilePath={locationState?.offerFilePath}
              imported={locationState?.imported}
            />
          }
        />
        <Route
          path="view"
          element={
            <OfferBuilderViewer
              state={locationState?.state}
              isMyOffer={locationState?.isMyOffer}
              offerData={locationState?.offerData}
              offerSummary={locationState?.offerSummary}
              offerFilePath={locationState?.offerFilePath}
              imported={locationState?.imported}
              referrerPath={locationState?.referrerPath}
            />
          }
        />
        <Route path="manage" element={<OfferManager />} />
        <Route path="/" element={<Navigate to="manage" />} />
      </Routes>
    </LayoutDashboardSub>
  );
}
