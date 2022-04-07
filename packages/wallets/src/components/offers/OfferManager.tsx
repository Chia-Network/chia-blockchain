import React, { useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import styled from 'styled-components';
import { Trans, t } from '@lingui/macro';
import moment from 'moment';
import BigNumber from 'bignumber.js';
import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom';
import {
  Back,
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
  mojoToCATLocaleString,
  useShowSaveDialog,
  Tooltip,
  LayoutDashboardSub,
} from '@chia/core';
import { OfferTradeRecord } from '@chia/api';
import fs from 'fs';
import { Remote } from 'electron';
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
  MenuItem,
  Typography
} from '@mui/material';
import { Cancel, GetApp as Download, Info, Reply as Share, Visibility } from '@mui/icons-material';
import { Trade as TradeIcon, Offers } from '@chia/icons';
import { useCancelOfferMutation, useGetOfferDataMutation, useGetWalletsQuery } from '@chia/api-react';
import { colorForOfferState, displayStringForOfferState, formatAmountForWalletType, suggestedFilenameForOffer } from './utils';
import useAssetIdName from '../../hooks/useAssetIdName';
import useWalletOffers from '../../hooks/useWalletOffers';
import { CreateOfferEditor } from './OfferEditor';
import { OfferImport } from './OfferImport';
import { OfferViewer } from './OfferViewer';
import OfferDataDialog from './OfferDataDialog';
import OfferShareDialog from './OfferShareDialog';
import OfferState from './OfferState';

const StyledTradeIcon = styled(TradeIcon)`
  font-size: 4rem;
`;

type OfferCancellationOptions = {
  cancelWithTransaction: boolean;
  cancellationFee: BigNumber;
};

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
  const [cancelWithTransaction, setCancelWithTransaction] = useState<boolean>(canCancelWithTransaction);

  function handleCancel() {
    onClose([false]);
  }

  async function handleConfirm() {
    const { fee: xchFee } = methods.getValues();

    const fee = cancelWithTransaction
      ? chiaToMojo(xchFee)
      : new BigNumber(0);

    onClose([true, { cancelWithTransaction, cancellationFee: fee }]);
  }

  return (
    <Dialog
      onClose={handleCancel}
      open={open}
      aria-labelledby="alert-dialog-title"
      aria-describedby="alert-dialog-description"
    >
      <DialogTitle id="alert-dialog-title"><Trans>Cancel Offer</Trans></DialogTitle>
      <DialogContent>
        <DialogContentText id="alert-dialog-description">
          <Form methods={methods} onSubmit={handleConfirm}>
            <Flex flexDirection="column" gap={3}>
              <Typography variant="body1">
                <Trans>
                  Are you sure you want to cancel your offer?
                </Trans>
              </Typography>
              {canCancelWithTransaction && (
                <>
                  <Typography variant="body1">
                    <Trans>
                      If you have already shared your offer file,
                      you may need to submit a transaction to cancel
                      the pending offer. Click "Cancel on blockchain"
                      to submit a cancellation transaction.
                    </Trans>
                  </Typography>
                  <Flex flexDirection="row" gap={3}>
                    <Grid container>
                      <Grid xs={6} item>
                        <FormControlLabel
                          control={<Checkbox name="cancelWithTransaction" checked={cancelWithTransaction} onChange={(event) => setCancelWithTransaction(event.target.checked)} />}
                          label={
                            <>
                              <Trans>Cancel on blockchain</Trans>{' '}
                              <TooltipIcon>
                                <Trans>
                                  Creates and submits a transaction on the blockchain that cancels the offer
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
        <Flex flexDirection="row" gap={3} style={{paddingBottom: '8px', paddingRight: '16px'}}>
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
  const { data: wallets, isLoading: isLoadingWallets } = useGetWalletsQuery();
  const { lookupByAssetId } = useAssetIdName();
  const openDialog = useOpenDialog();
  const navigate = useNavigate();
  const {
    offers,
    isLoading: isWalletOffersLoading,
    page,
    rowsPerPage,
    count,
    pageChange,
  } = useWalletOffers(5, 0, includeMyOffers, includeTakenOffers, 'RELEVANCE', false);

  async function handleShowOfferData(offerData: string) {
    openDialog((
      <OfferDataDialog offerData={offerData} />
    ));
  }

  async function handleExportOffer(tradeId: string) {
    const { data: response }: { data: { offer: string, tradeRecord: OfferTradeRecord, success: boolean } } = await getOfferData(tradeId);
    const { offer: offerData, tradeRecord, success } = response;
    if (success === true) {
      const dialogOptions = {
        defaultPath: suggestedFilenameForOffer(tradeRecord.summary, lookupByAssetId),
      }
      const remote: Remote = (window as any).remote;
      const result = await showSaveDialog(dialogOptions);
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
  }

  async function handleCancelOffer(tradeId: string, canCancelWithTransaction: boolean) {
    const [cancelConfirmed, cancellationOptions] = await openDialog(
      <ConfirmOfferCancellation
        canCancelWithTransaction={canCancelWithTransaction}
      />
    );

    if (cancelConfirmed === true) {
      const secure = canCancelWithTransaction ? cancellationOptions.cancelWithTransaction : false;
      const fee = canCancelWithTransaction ? cancellationOptions.cancellationFee : 0;
      await cancelOffer({ tradeId, secure: secure, fee: fee });
    }
  }

  function handleRowClick(event: any, row: OfferTradeRecord) {
    navigate('/dashboard/offers/view', {
      state: {
        tradeRecord: row
      },
    });
  }

  async function handleShare(event: any, row: OfferTradeRecord) {
    await openDialog((
      <OfferShareDialog
        offerRecord={row}
        offerData={row._offerData}
      />
    ));
  }

  const cols = useMemo(() => {
    return [
      {
        field: (row: OfferTradeRecord) => {
          const { status } = row;

          return (
            <Box onClick={(event) => handleRowClick(event, row)}>
              <Chip label={displayStringForOfferState(status)} variant="outlined" color={colorForOfferState(status)} />
            </Box>
          );
        },
        minWidth: '170px',
        maxWidth: '170px',
        title: <Trans>Status</Trans>
      },
      {
        field: (row: OfferTradeRecord) => {
          const resolvedOfferInfo = Object.entries(row.summary.offered).map(([assetId, amount]) => {
            const assetIdInfo = lookupByAssetId(assetId);
            const displayAmount = assetIdInfo ? formatAmountForWalletType(amount as number, assetIdInfo.walletType) : mojoToCATLocaleString(amount);
            const displayName = assetIdInfo?.displayName ?? t`Unknown CAT`;
            return {
              displayAmount,
              displayName,
            };
          });
          return (
            resolvedOfferInfo.map((info, index) => (
              <Flex flexDirection="row" gap={0.5} key={`${index}-${info.displayName}`}>
                <Typography variant="body2">{info.displayAmount}</Typography>
                <Typography noWrap variant="body2">{info.displayName}</Typography>
              </Flex>
            ))
          );
        },
        minWidth: '160px',
        title: <Trans>Offered</Trans>
      },
      {
        field: (row: OfferTradeRecord) => {
          const resolvedOfferInfo = Object.entries(row.summary.requested).map(([assetId, amount]) => {
            const assetIdInfo = lookupByAssetId(assetId);
            const displayAmount = assetIdInfo ? formatAmountForWalletType(amount as number, assetIdInfo.walletType) : mojoToCATLocaleString(amount);
            const displayName = assetIdInfo?.displayName ?? t`Unknown CAT`;
            return {
              displayAmount,
              displayName,
            };
          });
          return (
            resolvedOfferInfo.map((info, index) => (
              <Flex flexDirection="row" gap={0.5} key={`${index}-${info.displayName}`}>
                <Typography variant="body2">{info.displayAmount}</Typography>
                <Typography noWrap variant="body2">{info.displayName}</Typography>
              </Flex>
            ))
          );
        },
        minWidth: '160px',
        title: <Trans>Requested</Trans>
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
          const canCancel = status === OfferState.PENDING_ACCEPT || status === OfferState.PENDING_CONFIRM;
          const canShare = status === OfferState.PENDING_ACCEPT;
          const canCancelWithTransaction = canCancel && status === OfferState.PENDING_ACCEPT;

          return (
            <Flex flexDirection="row" justifyContent="center" gap={0}>
              <Flex style={{width: '32px'}}>
                {canShare && (
                  <Tooltip title={<Trans>Share</Trans>}>
                    <IconButton
                      size="small"
                      disabled={!canShare}
                      onClick={() => handleShare(undefined, row)}
                    >
                      <Share style={{transform: 'scaleX(-1)'}} />
                    </IconButton>
                  </Tooltip>
                )}
              </Flex>
              <Flex style={{width: '32px'}}>
                <More>
                  {({ onClose }: { onClose: () => void }) => (
                    <Box>
                      <MenuItem
                        onClick={() => {
                          onClose();
                          handleRowClick(undefined, row);
                        }}
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
                          onClick={() => {
                            onClose();
                            handleShowOfferData(row._offerData);
                          }}
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
                        <MenuItem
                          onClick={() => {
                            onClose();
                            handleExportOffer(tradeId);
                          }}
                        >
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
                          onClick={() => {
                            onClose();
                            handleCancelOffer(tradeId, canCancelWithTransaction);
                          }}
                        >
                          <ListItemIcon>
                            <Cancel fontSize="small" />
                          </ListItemIcon>
                          <Typography variant="inherit" noWrap>
                            <Trans>Cancel Offer</Trans>
                          </Typography>
                        </MenuItem>
                      )}
                    </Box>
                  )}
                </More>
              </Flex>
            </Flex>
          );
        },
        minWidth: '100px',
        maxWidth: '100px',
        title: <Flex justifyContent="center">Actions</Flex>
      },
    ];
  }, []);

  const hasOffers = !!offers?.length;

  return (
    <Card title={title} transparent>
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
          caption={!hasOffers && !isWalletOffersLoading && !isLoadingWallets && (
            <Typography variant="body2" align="center">
              <Trans>No current offers</Trans>
            </Typography>
          )}
        />
      </LoadingOverlay>
    </Card>
  );
}

export function OfferManager() {
  // const { data, isLoading } = useGetAllOffersQuery();
  const navigate = useNavigate();

  // const [myOffers, acceptedOffers]: OfferTradeRecord[] = useMemo(() => {
  //   if (isLoading || !data) {
  //     return [[], []];
  //   }

  //   // Show newest offers first
  //   const sortedOffers = [...data].sort((a: OfferTradeRecord, b: OfferTradeRecord) => b.createdAtTime - a.createdAtTime);
  //   const myOffers: OfferTradeRecord[] = [];
  //   const acceptedOffers: OfferTradeRecord[] = [];

  //   sortedOffers.forEach((offer) => {
  //     if (offer.isMyOffer) {
  //       myOffers.push(offer);
  //     }
  //     else {
  //       acceptedOffers.push(offer);
  //     }
  //   });

  //   return [myOffers, acceptedOffers];
  // }, [data, isLoading]);

  function handleCreateOffer() {
    navigate('/dashboard/offers/create');
  }

  function handleImportOffer() {
    navigate('/dashboard/offers/import');
  }

  return (
    <Flex flexDirection="column" gap={4}>
      <Flex gap={2} flexDirection="column">
        <Typography variant="h5">
          <Trans>Manage Offers</Trans>
        </Typography>
        <Grid container>
          <Grid xs={12} md={6} lg={5} item>
            <CardHero>
              <Offers color="primary" fontSize="extraLarge" />
              <Typography variant="body1">
                <Trans>
                  Create an offer to exchange XCH or other tokens. View an offer to inspect and accept an offer made by another party.
                </Trans>
              </Typography>
              <Button onClick={handleCreateOffer} variant="contained" color="primary">
                <Trans>Create an Offer</Trans>
              </Button>
              <Button onClick={handleImportOffer} variant="outlined">
                <Trans>View an Offer</Trans>
              </Button>
            </CardHero>
          </Grid>
        </Grid>
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
  const location: any = useLocation();
  const openDialog = useOpenDialog();

  async function handleOfferCreated(obj: { offerRecord: any, offerData: any }) {
    const { offerRecord, offerData } = obj;

    await openDialog(
      <OfferShareDialog
        offerRecord={offerRecord}
        offerData={offerData as string}
        showSuppressionCheckbox={true}
      />
    );
  }

  return (
    <LayoutDashboardSub>
      <Routes>
        <Route
          path="create"
          element={<CreateOfferEditor onOfferCreated={handleOfferCreated} />}
        />
        <Route path="import" element={<OfferImport />} />

        <Route path="view" element={(
          <OfferViewer
            tradeRecord={location?.state?.tradeRecord}
            offerData={location?.state?.offerData}
            offerSummary={location?.state?.offerSummary}
            offerFilePath={location?.state?.offerFilePath}
            imported={location?.state?.imported}
          />
        )} />
        <Route path="manage" element={<OfferManager />} />
        <Route path="/" element={<Navigate to="manage" /> } />
      </Routes>
    </LayoutDashboardSub>
  );
}
