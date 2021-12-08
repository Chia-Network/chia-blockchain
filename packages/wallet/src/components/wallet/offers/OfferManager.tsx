import React, { useEffect, useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import styled from 'styled-components';
import { Trans } from '@lingui/macro';
import moment from 'moment';
import { Switch, Route, useHistory, useRouteMatch, useLocation } from 'react-router-dom';
import {
  Back,
  Card,
  CardHero,
  ConfirmDialog,
  Fee,
  Flex,
  Form,
  LoadingOverlay,
  More,
  TableControlled,
  TooltipIcon,
  useOpenDialog,
} from '@chia/core';
import { OfferTradeRecord } from '@chia/api';
import {
  Box,
  Button,
  Checkbox,
  Chip,
  Divider,
  FormControlLabel,
  Grid,
  ListItemIcon,
  MenuItem,
  Typography
} from '@material-ui/core';
import { Cancel, GetApp as Download, Info, Visibility } from '@material-ui/icons';
import { Trade as TradeIcon } from '@chia/icons';
import { useCancelOfferMutation, useGetAllOffersQuery, useGetOfferDataMutation } from '@chia/api-react';
import { colorForOfferState, displayStringForOfferState, formatAmountForWalletType, suggestedFilenameForOffer } from './utils';
import useAssetIdName from '../../../hooks/useAssetIdName';
import { chia_to_mojo } from '../../../util/chia';
import { CreateOfferEditor } from './OfferEditor';
import { OfferImport } from './OfferImport';
import { OfferViewer } from './OfferViewer';
import OfferDataDialog from './OfferDataDialog';
import fs from 'fs';
import OfferState from './OfferState';

const StyledTradeIcon = styled(TradeIcon)`
  font-size: 4rem;
`;

type OfferCancellationOptions = {
  cancelWithTransaction: boolean;
  cancellationFee: number;
};

type ConfirmOfferCancellationProps = {
  onUpdateValues: (values: OfferCancellationOptions) => void;
};

function ConfirmOfferCancellation(props: ConfirmOfferCancellationProps) {
  const { onUpdateValues } = props;
  const methods = useForm({
    defaultValues: {
      cancelWithTransaction: true,
      fee: '',
    }
  });
  const { watch } = methods;
  const fee = watch('fee');
  const [cancelWithTransaction, setCancelWithTransaction] = useState<boolean>(true);

  // Communicate value updates to the parent component
  useEffect(() => {
    const feeInMojos = fee ? Number.parseFloat(chia_to_mojo(fee)) : 0;
    onUpdateValues({ cancelWithTransaction, cancellationFee: feeInMojos });
  }, [cancelWithTransaction, fee]);

  return (
    <Form methods={methods}>
      <Flex flexDirection="column" gap={3}>
        <Typography variant="body1">
          <Trans>
            Are you sure you want to cancel your offer?
          </Trans>
        </Typography>
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
            { cancelWithTransaction && (
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
      </Flex>
    </Form>
  );
}

type OfferListProps = {
  title: string | React.ReactElement;
  offers: OfferTradeRecord[];
  loading: boolean;
};

function OfferList(props: OfferListProps) {
  const { title, offers, loading } = props;
  const [getOfferData] = useGetOfferDataMutation();
  const [cancelOffer] = useCancelOfferMutation();
  const lookupAssetId = useAssetIdName();
  const openDialog = useOpenDialog();
  const history = useHistory();
  const [page, setPage] = useState<number>(0);
  const [rowsPerPage, setRowsPerPage] = useState<number>(5);

  function handlePageChange(rowsPerPage: number, page: number) {
    setRowsPerPage(rowsPerPage);
    setPage(page);
  }

  async function handleShowOfferData(offerData: string) {
    openDialog((
      <OfferDataDialog offerData={offerData} />
    ));
  }

  async function handleExportOffer(tradeId: string) {
    const { data: response } = await getOfferData(tradeId);
    const { offer: offerData, tradeRecord, success } = response;
    if (success === true) {
      const dialogOptions = {
        defaultPath: suggestedFilenameForOffer(tradeRecord),
      }
      const result = await window.remote.dialog.showSaveDialog(dialogOptions);
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

  async function handleCancelOffer(tradeId: string) {
    let options: OfferCancellationOptions = {
      cancelWithTransaction: false,
      cancellationFee: 0,
    };
    const cancelConfirmed = await openDialog(
      <ConfirmDialog
        title={<Trans>Cancel Offer</Trans>}
        confirmTitle={<Trans>Cancel Offer</Trans>}
        confirmColor="danger"
        cancelTitle={<Trans>Close</Trans>}
      >
        <ConfirmOfferCancellation
          onUpdateValues={(values) => options = values}
        />
      </ConfirmDialog>
    );

    if (cancelConfirmed === true) {
      await cancelOffer({ tradeId, secure: options.cancelWithTransaction, fee: options.cancellationFee });
    }
  }

  function handleRowClick(event: any, row: OfferTradeRecord) {
    history.push('/dashboard/wallets/offers/view', { tradeRecord: row });
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
            const assetIdInfo = lookupAssetId(assetId);
            return {
              displayAmount: (assetIdInfo ? formatAmountForWalletType(amount as number, assetIdInfo.walletType) : `${amount}`),
              displayName: (assetIdInfo ? assetIdInfo.displayName : 'unknown'),
            };
          });
          return (
            resolvedOfferInfo.map((info) => (
              <Flex flexDirection="row" gap={1}>
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
            const assetIdInfo = lookupAssetId(assetId);

            return {
              displayAmount: (assetIdInfo ? formatAmountForWalletType(amount as number, assetIdInfo.walletType) : `${amount}`),
              displayName: (assetIdInfo ? assetIdInfo.displayName : 'unknown'),
            };
          });
          return (
            resolvedOfferInfo.map((info) => (
              <Flex flexDirection="row" gap={1}>
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
          const { tradeId } = row;

          return (
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
                  {row.isMyOffer && (
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
                        <Trans>Export Offer File</Trans>
                      </Typography>
                    </MenuItem>
                  )}
                  {row.status === OfferState.PENDING_ACCEPT && (
                    <MenuItem
                      onClick={() => {
                        onClose();
                        handleCancelOffer(tradeId);
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
          );
        },
        minWidth: '100px',
        maxWidth: '100px',
        title: <Trans>Actions</Trans>
      },
    ];
  }, []);

  return (
    <Card title={title}>
      <LoadingOverlay loading={loading}>
        {offers.length ? (
          <TableControlled
            rows={offers.slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage)}
            cols={cols}
            rowsPerPageOptions={[5, 25, 100]}
            count={offers.length}
            rowsPerPage={rowsPerPage}
            pages={true}
            page={page}
            onPageChange={handlePageChange}
          />
        ) : (
          !loading && (
            <Typography variant="body2">
              <Trans>No current offers</Trans>
            </Typography>
          )
        )}
      </LoadingOverlay>
    </Card>
  );
}

export function OfferManager() {
  const { data, isLoading } = useGetAllOffersQuery();
  const history = useHistory();

  const [myOffers, acceptedOffers]: OfferTradeRecord[] = useMemo(() => {
    if (isLoading || !data) {
      return [[], []];
    }

    // Show newest offers first
    const sortedOffers = [...data].sort((a: OfferTradeRecord, b: OfferTradeRecord) => b.createdAtTime - a.createdAtTime);
    const myOffers: OfferTradeRecord[] = [];
    const acceptedOffers: OfferTradeRecord[] = [];

    sortedOffers.forEach((offer) => {
      if (offer.isMyOffer) {
        myOffers.push(offer);
      }
      else {
        acceptedOffers.push(offer);
      }
    });

    return [myOffers, acceptedOffers];
  }, [data, isLoading]);

  function handleCreateOffer() {
    history.push('/dashboard/wallets/offers/create');
  }

  function handleImportOffer() {
    history.push('/dashboard/wallets/offers/import');
  }

  return (
    <Flex flexDirection="column" gap={3}>
      <Flex flexGrow={1}>
        <Back variant="h5" to="/dashboard/wallets">
          <Trans>Manage Offers</Trans>
        </Back>
      </Flex>
      <Grid container>
        <Grid xs={12} md={6} lg={5} item>
          <CardHero>
            <StyledTradeIcon color="primary" />
            <Typography variant="body1">
              <Trans>
                Create an offer to exchange XCH or other tokens. View an offer to inspect and accept an offer made by another party.
              </Trans>
            </Typography>
            <Button onClick={handleCreateOffer} variant="contained" color="primary">
              <Trans>Create an Offer</Trans>
            </Button>
            <Button onClick={handleImportOffer} variant="contained" color="secondary">
              <Trans>View an Offer</Trans>
            </Button>
          </CardHero>
        </Grid>
      </Grid>
      <Divider />
      <OfferList title={<Trans>Your Offers</Trans>} offers={myOffers} loading={isLoading} />
      <OfferList title={<Trans>Accepted Offers</Trans>} offers={acceptedOffers} loading={isLoading} />
    </Flex>
  );
}

export function CreateOffer() {
  const { path } = useRouteMatch();
  const location: any = useLocation();

  return (
    <Switch>
      <Route path={`${path}/create`}>
        <CreateOfferEditor />
      </Route>
      <Route path={`${path}/import`}>
        <OfferImport />
      </Route>
      <Route path={`${path}/view`}>
        <OfferViewer
          tradeRecord={location?.state?.tradeRecord}
          offerData={location?.state?.offerData}
          offerSummary={location?.state?.offerSummary}
          offerFilePath={location?.state?.offerFilePath}
          imported={location?.state?.imported}
        />
      </Route>
      <Route path={`${path}/manage`}>
        <OfferManager />
      </Route>
    </Switch>
  );
}