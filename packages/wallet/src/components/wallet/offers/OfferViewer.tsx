import React, { useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { useHistory } from 'react-router-dom';
import moment from 'moment';
import { Trans, Plural, t } from '@lingui/macro';
import {
  AlertDialog,
  Back,
  ButtonLoading,
  Card,
  CopyToClipboard,
  Fee,
  Flex,
  Form,
  FormatLargeNumber,
  Link,
  TableControlled,
  TooltipIcon,
  useOpenDialog,
  useShowError
} from '@chia/core';
import {
  Box,
  Button,
  Divider,
  Grid,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableRow,
  Tooltip,
  Typography
} from '@material-ui/core';
import { OfferSummary, OfferTradeRecord } from '@chia/api';
import { useCheckOfferValidityMutation, useTakeOfferMutation } from '@chia/api-react';
import {
  colorForOfferState,
  displayStringForOfferState,
  formatAmountForWalletType
} from './utils';
import useAssetIdName from '../../../hooks/useAssetIdName';
import useOpenExternal from '../../../hooks/useOpenExternal';
import WalletType from '../../../constants/WalletType';
import { chia_to_mojo, mojo_to_chia_string } from '../../../util/chia';
import OfferCoinOfInterest from 'types/OfferCoinOfInterest';
import OfferState from './OfferState';
import styled from 'styled-components';

const StyledViewerBox = styled.div`
  padding: ${({ theme }) => `${theme.spacing(4)}px`};
`;

const StyledSummaryBox = styled.div`
  padding-left: ${({ theme }) => `${theme.spacing(2)}px`};
  padding-right: ${({ theme }) => `${theme.spacing(2)}px`};
`;

const StyledHeaderBox = styled.div`
  padding-top: ${({ theme }) => `${theme.spacing(1)}px`};
  padding-bottom: ${({ theme }) => `${theme.spacing(1)}px`};
  padding-left: ${({ theme }) => `${theme.spacing(2)}px`};
  padding-right: ${({ theme }) => `${theme.spacing(2)}px`};
  border-radius: 4px;
  background-color: ${({ theme }) => theme.palette.background.paper};
`;

type OfferMojoAmountProps = {
  mojos: number;
  mojoThreshold?: number
};

function OfferMojoAmount(props: OfferMojoAmountProps): React.ReactElement{
  const { mojos, mojoThreshold } = props;

  return (
    <>
      { mojoThreshold && mojos < mojoThreshold && (
        <Flex flexDirection="row" flexGrow={1} gap={1}>
          (
          <FormatLargeNumber value={mojos} />
          <Box>
            <Plural value={mojos} one="mojo" other="mojos" />
          </Box>
          )
        </Flex>
      )}
    </>
  );
}

OfferMojoAmount.defaultProps = {
  mojos: 0,
  mojoThreshold: 1000000000,  // 1 billion
};

type OfferDetailsProps = {
  tradeRecord?: OfferTradeRecord;
  offerData?: string;
  offerSummary?: OfferSummary;
  imported?: boolean;
};

type OfferDetailsRow = {
  name: React.ReactElement;
  value: any;
  color?:
      | 'initial'
      | 'inherit'
      | 'primary'
      | 'secondary'
      | 'textPrimary'
      | 'textSecondary'
      | 'error';
  tooltip?: React.ReactElement;
};

function OfferDetails(props: OfferDetailsProps) {
  const { tradeRecord, offerData, offerSummary, imported } = props;
  const summary = tradeRecord?.summary || offerSummary;
  const lookupAssetId = useAssetIdName();
  const openExternal = useOpenExternal();
  const history = useHistory();
  const openDialog = useOpenDialog();
  const showError = useShowError();
  const methods = useForm({ defaultValues: { fee: '' } });
  const [isAccepting, setIsAccepting] = useState<boolean>(false);
  const [isValidating, setIsValidating] = useState<boolean>(false);
  const [isValid, setIsValid] = useState<boolean>(tradeRecord !== undefined);
  const [checkOfferValidity] = useCheckOfferValidityMutation();
  const [takeOffer] = useTakeOfferMutation();
  let detailRows: OfferDetailsRow[] = [];

  useMemo(async () => {
    if (!offerData) {
      return false;
    }

    let valid = false;

    try {
      setIsValidating(true);

      const response = await checkOfferValidity(offerData);

      if (response.data?.success === true) {
        valid = response.data?.valid === true;
      }
      else {
        showError(response.data?.error ?? new Error("Encountered an unknown error while checking offer validity"));
      }
    }
    catch (e) {
      showError(e);
    }
    finally {
      setIsValid(valid);
      setIsValidating(false);
    }
  }, [offerData]);

  if (tradeRecord) {
    detailRows.push({
      name: <Trans>Status</Trans>,
      value: displayStringForOfferState(tradeRecord.status),
      color: colorForOfferState(tradeRecord.status),
    });

    detailRows.push({
      name: <Trans>Offer Identifier</Trans>,
      value: tradeRecord.tradeId,
    });

    detailRows.push({
      name: <Trans>Confirmed at Height</Trans>,
      value: tradeRecord.confirmedAtIndex || <Trans>Not confirmed</Trans>,
    });

    if (!tradeRecord.isMyOffer) {
      detailRows.push({
        name: <Trans>Accepted on Date</Trans>,
        value: tradeRecord.acceptedAtTime ? (
          moment(tradeRecord.acceptedAtTime * 1000).format('LLL')
        ) : (
          <Trans>Not accepted</Trans>
        ),
      });
    }

    detailRows.push({
      name: <Trans>Creation Date</Trans>,
      value: moment(tradeRecord.createdAtTime * 1000).format('LLL'),
    });

    detailRows.push({
      name: <Trans>Node Count</Trans>,
      tooltip: <Trans>This number reflects the number of nodes that the accepted SpendBundle has been sent to</Trans>,
      value: tradeRecord.sent,
    });
  }

  const coinCols = [
    {
      field: (coin: OfferCoinOfInterest) => {
        return (
          <Typography variant="body2">
            <Flex flexDirection="row" flexGrow={1} gap={1}>
              {mojo_to_chia_string(coin.amount)}
            </Flex>
          </Typography>
        )
      },
      title: <Trans>Amount</Trans>
    },
    {
      field: (coin: OfferCoinOfInterest) => {
        return (
          <Tooltip
            title={
              <Flex alignItems="center" gap={1}>
                <Box maxWidth={200}>{coin.parentCoinInfo}</Box>
                <CopyToClipboard value={coin.parentCoinInfo} fontSize="small" />
              </Flex>
            }
            interactive
          >
            <Link
              onClick={(event: React.SyntheticEvent) => handleLinkClicked(event, `https://www.chiaexplorer.com/blockchain/coin/${coin.parentCoinInfo}`)}
            >
              {coin.parentCoinInfo}
            </Link>
          </Tooltip>
        )
      },
      minWidth: '200px',
      title: <Trans>Parent Coin</Trans>
    },
    {
      field: (coin: OfferCoinOfInterest) => {
        return (
          <Tooltip
            title={
              <Flex alignItems="center" gap={1}>
                <Box maxWidth={200}>{coin.puzzleHash}</Box>
                <CopyToClipboard value={coin.puzzleHash} fontSize="small" />
              </Flex>
            }
            interactive
          >
            <Link
              onClick={(event: React.SyntheticEvent) => handleLinkClicked(event, `https://www.chiaexplorer.com/blockchain/puzzlehash/${coin.puzzleHash}`)}
            >
              {coin.puzzleHash}
            </Link>
          </Tooltip>
        )
      },
      fullWidth: true,
      title: <Trans>Puzzle Hash</Trans>
    }
  ];

  function handleLinkClicked(event: React.SyntheticEvent, url: string) {
    event.preventDefault();
    event.stopPropagation();
    openExternal(url);
  }

  async function handleAcceptOffer(formData: any) {
    const { fee } = formData;
    const feeInMojos = fee ? Number.parseFloat(chia_to_mojo(fee)) : 0;

    try {
      setIsAccepting(true);

      const response = await takeOffer({ offer: offerData, fee: feeInMojos });

      if (response.data?.success === true) {
        await openDialog(
          <AlertDialog title={<Trans>Success</Trans>}>
            {response.message ?? <Trans>Offer has been accepted and is awaiting confirmation.</Trans>}
          </AlertDialog>,
        );
      }
      else {
        throw new Error(response.error?.message ?? 'Something went wrong');
      }

      history.replace('/dashboard/wallets/offers/manage');
    }
    catch (e) {
      let error = e as Error;

      if (error.message.startsWith('insufficient funds')) {
        error = new Error(t`
          Insufficient funds available to accept offer. Ensure that your
          spendable balance is sufficient to cover the offer amount.
        `);
      }
      showError(error);
    }
    finally {
      setIsAccepting(false);
    }
  }

  type OfferHeaderProps = {
    isMyOffer: boolean;
    isInvalid: boolean;
    isComplete: boolean;
  };

  function OfferHeader(props: OfferHeaderProps) {
    const { isMyOffer, isInvalid, isComplete } = props;
    let headerElement: React.ReactElement | undefined = undefined;

    if (isMyOffer) {
      headerElement = <Typography variant="subtitle1" color="primary"><Trans>You created this offer</Trans></Typography>
    }

    if (!headerElement && isInvalid) {
      headerElement = <Typography variant="subtitle1" color="error"><Trans>This offer is no longer valid</Trans></Typography>
    }

    if (!headerElement && isComplete) {
      headerElement = <Typography variant="subtitle1" color="primary"><Trans>This offer has completed successfully</Trans></Typography>
    }

    return headerElement ? (
      <StyledHeaderBox>
        <Flex flexDirection="column" flexGrow={1} gap={3}>
          {headerElement}
        </Flex>
      </StyledHeaderBox>
    ) : (
      <></>
    );
  }

  OfferHeader.defaultProps = {
    isMyOffer: false,
    isInvalid: false,
    isComplete: false,
  };

  function OfferSummaryEntry({ assetId, amount, ...rest}: { assetId: string, amount: number }) {
    const assetIdInfo = lookupAssetId(assetId);
    const displayAmount = assetIdInfo ? formatAmountForWalletType(amount as number, assetIdInfo.walletType) : `${amount}`;
    const displayName = assetIdInfo?.displayName ?? 'unknown';

    return (
      <Flex flexDirections="row" gap={1}>
        <Typography variant="body1" {...rest}>
          {displayAmount} {displayName}
        </Typography>
        {assetIdInfo?.walletType === WalletType.STANDARD_WALLET && (
          <Typography variant="body1" color="textSecondary">
            <OfferMojoAmount mojos={amount} />
          </Typography>
        )}
      </Flex>
    );
  }

  return (
    <StyledViewerBox>
      <Flex flexDirection="column" gap={3}>
        <OfferHeader
          isMyOffer={tradeRecord?.isMyOffer}
          isInvalid={!isValidating && !isValid}
          isComplete={tradeRecord?.status === OfferState.CONFIRMED}
        />
        {summary && (
          <Card title={<Trans>Summary</Trans>}>
            <StyledSummaryBox>
              <Flex flexDirection="column" flexGrow={1} gap={3}>
                <Typography variant="h6">In exchange for</Typography>
                {Object.entries(summary.requested).map(([assetId, amount]) => (
                  <OfferSummaryEntry assetId={assetId} amount={amount as number} />
                ))}
                <Divider />
                <Typography variant="h6">You will receive</Typography>
                {Object.entries(summary.offered).map(([assetId, amount]) => (
                  <OfferSummaryEntry assetId={assetId} amount={amount as number} />
                ))}
                {imported && (
                  <Form methods={methods} onSubmit={handleAcceptOffer}>
                    <Flex flexDirection="column" gap={3}>
                      <Divider />
                      {isValid && (
                        <Grid direction="column" md={6} container>
                          <Fee
                            id="filled-secondary"
                            variant="filled"
                            name="fee"
                            color="secondary"
                            label={<Trans>Fee</Trans>}
                            disabled={isAccepting}
                            fullwidth
                          />
                        </Grid>
                      )}
                      <Flex flexDirection="row" gap={3}>
                        <Button
                          variant="contained"
                          color="secondary"
                          onClick={() => history.goBack()}
                          disabled={isAccepting}
                        >
                          <Trans>Back</Trans>
                        </Button>
                        <ButtonLoading
                          variant="contained"
                          color="primary"
                          type="submit"
                          disabled={!isValid}
                          loading={isAccepting}
                        >
                          <Trans>Accept Offer</Trans>
                        </ButtonLoading>
                      </Flex>
                    </Flex>
                  </Form>
                )}
              </Flex>
            </StyledSummaryBox>
          </Card>
        )}
        {tradeRecord && (
          <Card title={<Trans>Details</Trans>}>
            <TableContainer component={Paper}>
              <Table>
                <TableBody>
                  {detailRows.map((row, index) => (
                    <TableRow key={index}>
                      <TableCell component="th" scope="row">
                        {row.name}{' '}
                        {row.tooltip && <TooltipIcon>{row.tooltip}</TooltipIcon>}
                      </TableCell>
                      <TableCell align="right">
                        <Typography variant="body2" color={row.color}>
                          {row.value}
                        </Typography>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Card>
        )}
        {tradeRecord && tradeRecord.coinsOfInterest?.length > 0 && (
          <Card title={<Trans>Coins</Trans>}>
            <TableControlled
              rows={tradeRecord.coinsOfInterest}
              cols={coinCols}
            />
          </Card>
        )}
      </Flex>
    </StyledViewerBox>
  );
}

type OfferViewerProps = {
  tradeRecord?: OfferTradeRecord;
  offerData?: string;
  offerSummary?: OfferSummary;
  offerFilePath?: string;
  imported?: boolean;
};

export function OfferViewer(props: OfferViewerProps) {
  const { offerData, offerFilePath, offerSummary, tradeRecord, imported, ...rest } = props;

  return (
    <Grid container>
      <Flex flexDirection="column" flexGrow={1} gap={3}>
        <Flex>
          <Back variant="h5">
            {offerFilePath ? (
              <Trans>Viewing offer: {offerFilePath}</Trans>
            ) : (
              tradeRecord ? (
                <Trans>Viewing offer created at {moment(tradeRecord.createdAtTime * 1000).format('LLL')}</Trans>
              ) : (
                <Trans>Viewing offer</Trans>
              )
            )}
          </Back>
        </Flex>
        <OfferDetails
          tradeRecord={tradeRecord}
          offerData={offerData}
          offerSummary={offerSummary}
          imported={imported}
          {...rest}
        />
      </Flex>
    </Grid>
  );
}