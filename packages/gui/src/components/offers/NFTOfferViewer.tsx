import React, { useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate } from 'react-router-dom';
import BigNumber from 'bignumber.js';
import { Plural, Trans, t } from '@lingui/macro';
import {
  useCheckOfferValidityMutation,
  useGetNFTInfoQuery,
  useGetNFTWallets,
} from '@chia/api-react';
import type { Wallet } from '@chia/api';
import { OfferSummaryRecord, OfferTradeRecord } from '@chia/api';
import {
  Back,
  Button,
  ButtonLoading,
  Fee,
  Flex,
  Form,
  FormatLargeNumber,
  StateColor,
  Tooltip,
  TooltipIcon,
  catToMojo,
  chiaToMojo,
  mojoToChia,
  useColorModeValue,
  useShowError,
} from '@chia/core';
import { Box, Divider, Grid, Typography } from '@mui/material';
import { Warning as WarningIcon } from '@mui/icons-material';
import { useTheme } from '@mui/material/styles';
import useAcceptOfferHook from '../../hooks/useAcceptOfferHook';
import useAssetIdName from '../../hooks/useAssetIdName';
import useFetchNFTs from '../../hooks/useFetchNFTs';
import { stripHexPrefix } from '../../util/utils';
import { convertRoyaltyToPercentage, launcherIdToNFTId } from '../../util/nfts';
import {
  calculateNFTRoyalties,
  determineNFTOfferExchangeType,
  getNFTPriceWithoutRoyalties,
  offerAssetTypeForAssetId,
} from './utils';
import OfferAsset from './OfferAsset';
import OfferHeader from './OfferHeader';
import OfferState from './OfferState';
import { OfferSummaryNFTRow, OfferSummaryTokenRow } from './OfferSummaryRow';
import OfferViewerTitle from './OfferViewerTitle';
import NFTOfferExchangeType from './NFTOfferExchangeType';
import NFTOfferPreview from './NFTOfferPreview';
import styled from 'styled-components';

/* ========================================================================== */

const StyledWarningText = styled(Typography)`
  color: ${StateColor.WARNING};
`;

const StyledWarningIcon = styled(WarningIcon)`
  color: ${StateColor.WARNING};
`;

/* ========================================================================== */

type NFTOfferSummaryRowProps = {
  title: React.ReactElement | string;
  summaryKey: string;
  summary: any;
  unknownAssets?: string[];
  rowIndentation: number;
  showNFTPreview: boolean;
  overrideNFTSellerAmount?: number;
};

function NFTOfferSummaryRow(props: NFTOfferSummaryRowProps) {
  const {
    title,
    summaryKey,
    summary,
    unknownAssets,
    rowIndentation = 0,
    showNFTPreview = false,
    overrideNFTSellerAmount,
  } = props;
  const theme = useTheme();
  const horizontalPadding = `${theme.spacing(rowIndentation)}`; // logic borrowed from Flex's gap computation
  const summaryData: { [key: string]: number } = summary[summaryKey];
  const summaryInfo = summary.infos;
  const assetIdsToTypes: { [key: string]: OfferAsset | undefined }[] =
    useMemo(() => {
      return Object.keys(summaryData).map((key) => {
        const infoDict = summaryInfo[key];
        let assetType: OfferAsset | undefined;

        if (['xch', 'txch'].includes(key.toLowerCase())) {
          assetType = OfferAsset.CHIA;
        } else if (infoDict?.type) {
          switch (infoDict.type.toLowerCase()) {
            case 'singleton':
              assetType = OfferAsset.NFT;
              break;
            case 'cat':
              assetType = OfferAsset.TOKEN;
              break;
            default:
              console.log(`Unknown asset type: ${infoDict.type}`);
              break;
          }
        } else {
          console.log(`Unknown asset: ${key}`);
        }

        return { [key]: assetType };
      });
    }, [summaryData, summaryInfo]);

  const rows: (React.ReactElement | null)[] = assetIdsToTypes.map((entry) => {
    const [assetId, assetType]: [string, OfferAsset | undefined] =
      Object.entries(entry)[0];

    switch (assetType) {
      case undefined:
        return null;
      case OfferAsset.CHIA: // fall-through
      case OfferAsset.TOKEN:
        return (
          <OfferSummaryTokenRow
            assetId={assetId}
            amount={summaryData[assetId]}
            overrideNFTSellerAmount={overrideNFTSellerAmount}
          />
        );
      case OfferAsset.NFT:
        return (
          <OfferSummaryNFTRow
            launcherId={assetId}
            amount={summaryData[assetId]}
            showNFTPreview={showNFTPreview}
          />
        );
      default:
        console.log(`Unhandled OfferAsset type: ${assetType}`);
        return (
          <div>
            <Typography variant="h5">
              <Trans>Unrecognized asset</Trans>
            </Typography>
          </div>
        );
    }
  });

  if (unknownAssets?.length ?? 0 > 0) {
    console.log('Unknown assets');
    console.log(unknownAssets);
  }

  return (
    <Flex flexDirection="column" gap={2}>
      <Flex flexDirection="column" gap={2}>
        {title}
        <Box
          sx={{
            marginLeft: `${horizontalPadding}`,
            marginRight: `${horizontalPadding}`,
          }}
        >
          {rows.map((row, index) => (
            <div key={index}>{row}</div>
          ))}
        </Box>
      </Flex>
      {unknownAssets !== undefined && unknownAssets.length > 0 && (
        <Flex flexDirection="row" gap={1}>
          <StyledWarningText variant="caption">
            <Trans>
              Offer cannot be accepted because you don&apos;t possess the
              requested assets
            </Trans>
          </StyledWarningText>
        </Flex>
      )}
    </Flex>
  );
}

/* ========================================================================== */
/*                             NFT Offer Maker Fee                            */
/* ========================================================================== */

type NFTOfferMakerFeeProps = {
  makerFee: number;
  imported: boolean;
};

function NFTOfferMakerFee(props: NFTOfferMakerFeeProps) {
  const { makerFee, imported } = props;

  if (!makerFee) {
    return null;
  }

  return (
    <Flex flexDirection="row" alignItems="center" gap={1}>
      <Typography
        variant="body1"
        color="secondary"
        style={{ fontWeight: 'bold' }}
      >
        <Trans>Fees included in offer:</Trans>
      </Typography>
      <Typography color="primary">
        <FormatLargeNumber value={makerFee} />
      </Typography>
      <Typography>
        <Plural value={makerFee} one="mojo" other="mojos" />
      </Typography>
      <TooltipIcon>
        {imported ? (
          <Trans>
            This offer has a fee included to help expedite the transaction when
            the offer is accepted. You may specify an additional fee if you feel
            that the included fee is too small.
          </Trans>
        ) : (
          <Trans>
            This offer has a fee included to help expedite the transaction when
            the offer is accepted.
          </Trans>
        )}
      </TooltipIcon>
    </Flex>
  );
}

/* ========================================================================== */
/*                              NFT Offer Summary                             */
/* ========================================================================== */

type NFTOfferSummaryProps = {
  isMyOffer: boolean;
  imported: boolean;
  summary: any;
  title?: React.ReactElement | string;
  makerTitle: React.ReactElement | string;
  takerTitle: React.ReactElement | string;
  rowIndentation: number;
  setIsMissingRequestedAsset?: (isMissing: boolean) => void;
  showNFTPreview?: boolean;
  showMakerFee?: boolean;
  overrideNFTSellerAmount?: number;
};

export function NFTOfferSummary(props: NFTOfferSummaryProps) {
  const {
    isMyOffer,
    imported,
    summary,
    title,
    makerTitle,
    takerTitle,
    rowIndentation = 0,
    setIsMissingRequestedAsset,
    showNFTPreview = false,
    showMakerFee = true,
    overrideNFTSellerAmount,
  } = props;
  const { lookupByAssetId } = useAssetIdName();
  const { wallets: nftWallets } = useGetNFTWallets();
  const { nfts, isLoading: isLoadingNFTs } = useFetchNFTs(
    nftWallets.map((wallet: Wallet) => wallet.id),
  );
  const makerEntries: [string, number][] = Object.entries(summary.offered);
  const takerEntries: [string, number][] = Object.entries(summary.requested);
  const [takerUnknownAssets, makerUnknownAssets] = useMemo(() => {
    if (isMyOffer || isLoadingNFTs) {
      return [];
    }
    const takerUnknownAssets = makerEntries
      .filter(
        ([assetId]) =>
          offerAssetTypeForAssetId(assetId, summary) !== OfferAsset.NFT &&
          lookupByAssetId(assetId) === undefined,
      )
      .map(([assetId]) => assetId);

    const makerUnknownAssets = takerEntries
      .filter(([assetId]) => {
        const assetType = offerAssetTypeForAssetId(assetId, summary);
        if (assetType === OfferAsset.NFT) {
          return (
            nfts.find(
              (nft) =>
                stripHexPrefix(nft.launcherId.toLowerCase()) ===
                assetId.toLowerCase(),
            ) === undefined
          );
        }
        return lookupByAssetId(assetId) === undefined;
      })
      .map(([assetId]) => assetId);

    return [takerUnknownAssets, makerUnknownAssets];
  }, [
    isMyOffer,
    isLoadingNFTs,
    makerEntries,
    takerEntries,
    summary,
    lookupByAssetId,
    nfts,
  ]);
  const makerSummary: React.ReactElement = (
    <NFTOfferSummaryRow
      title={makerTitle}
      summaryKey={isMyOffer ? 'requested' : 'offered'}
      summary={summary}
      unknownAssets={isMyOffer ? undefined : takerUnknownAssets}
      rowIndentation={rowIndentation}
      showNFTPreview={showNFTPreview}
      overrideNFTSellerAmount={overrideNFTSellerAmount}
    />
  );
  const takerSummary: React.ReactElement = (
    <NFTOfferSummaryRow
      title={takerTitle}
      summaryKey={isMyOffer ? 'offered' : 'requested'}
      summary={summary}
      unknownAssets={isMyOffer ? undefined : makerUnknownAssets}
      rowIndentation={rowIndentation}
      showNFTPreview={showNFTPreview}
      overrideNFTSellerAmount={overrideNFTSellerAmount}
    />
  );
  const makerFee: number = summary.fees;
  const summaries: React.ReactElement[] = [makerSummary, takerSummary];

  if (setIsMissingRequestedAsset) {
    const isMissingRequestedAsset = isMyOffer
      ? false
      : makerUnknownAssets?.length !== 0 ?? false;

    setIsMissingRequestedAsset(isMissingRequestedAsset);
  }

  if (isMyOffer) {
    summaries.reverse();
  }

  return (
    <Flex flexDirection="column" gap={2}>
      {title}
      {summaries.map((summary, index) => (
        <Flex flexDirection="column" key={index} gap={2}>
          {summary}
          {index !== summaries.length - 1 && <Divider />}
        </Flex>
      ))}
      {showMakerFee && (
        <Flex flexDirection="column" gap={2}>
          <Divider />
          <NFTOfferMakerFee makerFee={makerFee} imported={imported} />
        </Flex>
      )}
    </Flex>
  );
}

/* ========================================================================== */
/*                              NFT Offer Details                             */
/* ========================================================================== */

type NFTOfferDetailsProps = {
  tradeRecord?: OfferTradeRecord;
  offerData?: string;
  offerSummary?: OfferSummaryRecord;
  imported?: boolean;
};

function NFTOfferDetails(props: NFTOfferDetailsProps) {
  const { tradeRecord, offerData, offerSummary, imported } = props;
  const summary = tradeRecord?.summary || offerSummary;
  const exchangeType = determineNFTOfferExchangeType(summary);
  const makerFee: number = summary.fees;
  const isMyOffer = !!tradeRecord?.isMyOffer;
  const showError = useShowError();
  const methods = useForm({ defaultValues: { fee: '' } });
  const navigate = useNavigate();
  const theme = useTheme();
  const [acceptOffer] = useAcceptOfferHook();
  const [isAccepting, setIsAccepting] = useState<boolean>(false);
  const [isValidating, setIsValidating] = useState<boolean>(false);
  const [isValid, setIsValid] = useState<boolean>(tradeRecord !== undefined);
  const [isMissingRequestedAsset, setIsMissingRequestedAsset] =
    useState<boolean>(false);
  const [checkOfferValidity] = useCheckOfferValidityMutation();
  const driverDict: { [key: string]: any } = summary?.infos ?? {};
  const launcherId: string | undefined = Object.keys(driverDict).find(
    (id: string) => driverDict[id].launcherId?.length > 0,
  );
  const nftId: string | undefined = launcherId
    ? launcherIdToNFTId(launcherId)
    : undefined;
  const { data: nft } = useGetNFTInfoQuery({ coinId: launcherId });
  const { amount, assetId, assetType } =
    getNFTPriceWithoutRoyalties(summary) ?? {};
  const { lookupByAssetId } = useAssetIdName();
  const assetIdInfo = assetId ? lookupByAssetId(assetId) : undefined;
  const displayName = assetIdInfo?.displayName ?? t`Unknown CAT`;

  const nftSaleInfo = useMemo(() => {
    if (
      !exchangeType ||
      amount === undefined ||
      !nft ||
      nft.royaltyPercentage === undefined
    ) {
      return undefined;
    }

    const royaltyPercentage = convertRoyaltyToPercentage(nft.royaltyPercentage);
    const xchMakerFee = mojoToChia(makerFee);

    return {
      ...calculateNFTRoyalties(
        amount,
        parseFloat(xchMakerFee),
        convertRoyaltyToPercentage(nft.royaltyPercentage),
        exchangeType,
      ),
      royaltyPercentage,
    };
  }, [nft]);
  const showRoyaltyWarning = (nftSaleInfo?.royaltyPercentage ?? 0) >= 20;
  const royaltyPercentageColor = showRoyaltyWarning
    ? StateColor.WARNING
    : 'textSecondary';
  const overrideNFTSellerAmount =
    exchangeType === NFTOfferExchangeType.TokenForNFT
      ? assetType === OfferAsset.CHIA
        ? chiaToMojo(nftSaleInfo?.nftSellerNetAmount ?? 0)
        : catToMojo(nftSaleInfo?.nftSellerNetAmount ?? 0)
      : undefined;

  useMemo(async () => {
    if (!offerData) {
      return;
    }

    let valid = false;

    try {
      setIsValidating(true);

      const response = await checkOfferValidity(offerData);

      if (response.data?.success === true) {
        valid = response.data?.valid === true;
      } else {
        showError(
          response.data?.error ??
            new Error(
              'Encountered an unknown error while checking offer validity',
            ),
        );
      }
    } catch (e) {
      showError(e);
    } finally {
      setIsValid(valid);
      setIsValidating(false);
    }
  }, [offerData]);

  async function handleAcceptOffer(formData: any) {
    const { fee } = formData;

    if (!offerData) {
      console.log('No offer data to accept');
      return;
    }

    await acceptOffer(
      offerData,
      summary,
      fee,
      (accepting: boolean) => setIsAccepting(accepting),
      () => navigate('/dashboard/offers'),
    );
  }

  return (
    <Form methods={methods} onSubmit={handleAcceptOffer}>
      <Flex flexDirection="column" flexGrow={1} gap={4}>
        <OfferHeader
          isMyOffer={isMyOffer}
          isInvalid={!isValidating && !isValid}
          isComplete={tradeRecord?.status === OfferState.CONFIRMED}
        />

        <Flex
          flexDirection="column"
          flexGrow={1}
          gap={1}
          sx={{
            border: `1px solid ${useColorModeValue(theme, 'border')}`,
            borderRadius: '4px',
            bgcolor: 'background.paper',
            boxShadow:
              '0px 2px 1px -1px rgb(0 0 0 / 20%), 0px 1px 1px 0px rgb(0 0 0 / 14%), 0px 1px 3px 0px rgb(0 0 0 / 12%)',
            overflow: 'hidden',
          }}
        >
          <Flex direction="row">
            <Flex
              flexDirection="column"
              flexGrow={1}
              gap={3}
              style={{ padding: '1em' }}
            >
              <NFTOfferSummary
                isMyOffer={isMyOffer}
                imported={!!imported}
                summary={summary}
                title={
                  <Typography variant="h6" style={{ fontWeight: 'bold' }}>
                    <Trans>Purchase Summary</Trans>
                  </Typography>
                }
                makerTitle={
                  <Typography variant="body1" color="textSecondary">
                    <Trans>You will receive</Trans>
                  </Typography>
                }
                takerTitle={
                  <Typography variant="body1" color="textSecondary">
                    <Trans>In exchange for</Trans>
                  </Typography>
                }
                setIsMissingRequestedAsset={(isMissing: boolean) =>
                  setIsMissingRequestedAsset(isMissing)
                }
                rowIndentation={0}
                showNFTPreview={false}
                showMakerFee={false}
                overrideNFTSellerAmount={overrideNFTSellerAmount}
              />
              <Divider />
              <Flex flexDirection="column" gap={2}>
                {nftSaleInfo && (
                  <>
                    <Flex flexDirection="column" gap={1}>
                      <Typography variant="body1" color="textSecondary">
                        <Trans>NFT Purchase Price</Trans>
                      </Typography>
                      <Typography variant="body1">
                        <>
                          <FormatLargeNumber
                            value={
                              new BigNumber(
                                exchangeType ===
                                NFTOfferExchangeType.NFTForToken
                                  ? nftSaleInfo?.nftSellerNetAmount ?? 0
                                  : amount ?? 0,
                              )
                            }
                          />{' '}
                          {displayName}
                        </>
                      </Typography>
                    </Flex>
                    <Flex flexDirection="column" gap={1}>
                      <Flex flexDirection="row" alignItems="center" gap={1}>
                        <Typography
                          variant="body1"
                          color={royaltyPercentageColor}
                        >
                          <Trans>
                            Creator Fee ({`${nftSaleInfo?.royaltyPercentage}%)`}
                          </Trans>
                        </Typography>
                        {showRoyaltyWarning && (
                          <Tooltip
                            title={
                              <Trans>
                                Creator royalty percentage seems high
                              </Trans>
                            }
                          >
                            <StyledWarningIcon fontSize="small" />
                          </Tooltip>
                        )}
                      </Flex>
                      <Typography variant="subtitle1">
                        <FormatLargeNumber
                          value={
                            new BigNumber(nftSaleInfo?.royaltyAmountString ?? 0)
                          }
                        />{' '}
                        {displayName}
                      </Typography>
                    </Flex>
                  </>
                )}
                <NFTOfferMakerFee makerFee={makerFee} imported={!!imported} />
              </Flex>
              {nftSaleInfo && (
                <>
                  <Divider />
                  <Flex flexDirection="column" gap={0.5}>
                    <Flex flexDirection="row" alignItems="center" gap={1}>
                      {exchangeType === NFTOfferExchangeType.NFTForToken ? (
                        <Typography variant="h6" color="textSecondary">
                          <Trans>Total Amount Requested</Trans>
                        </Typography>
                      ) : (
                        <Typography variant="subtitle1" color="textSecondary">
                          <Trans>Total Amount Offered</Trans>
                        </Typography>
                      )}
                      <Flex justifyContent="center">
                        <TooltipIcon>
                          {exchangeType === NFTOfferExchangeType.NFTForToken ? (
                            <Trans>
                              The total amount requested includes the asking
                              price, plus the associated creator fees (if the
                              NFT has royalty payments enabled).
                              {imported ? (
                                <>
                                  <p />
                                  The optional network fee is not included in
                                  this total.
                                </>
                              ) : null}
                            </Trans>
                          ) : (
                            <Trans>
                              The total amount offered includes the offered
                              purchase price, plus the optional offer creation
                              fee.
                              <p />
                              If the NFT has royalty payments enabled, those
                              creator fees will be paid from the offered
                              purchase price.
                            </Trans>
                          )}
                        </TooltipIcon>
                      </Flex>
                    </Flex>
                    <Typography
                      variant={
                        exchangeType === NFTOfferExchangeType.NFTForToken
                          ? 'h5'
                          : 'h6'
                      }
                      fontWeight={
                        exchangeType === NFTOfferExchangeType.NFTForToken
                          ? 'bold'
                          : 'regular'
                      }
                    >
                      <FormatLargeNumber
                        value={
                          new BigNumber(nftSaleInfo?.totalAmountString ?? 0)
                        }
                      />{' '}
                      {displayName}
                    </Typography>
                  </Flex>
                  {exchangeType === NFTOfferExchangeType.TokenForNFT && (
                    <Flex flexDirection="column" gap={0.5}>
                      <Flex flexDirection="row" alignItems="center" gap={1}>
                        <Typography variant="h6" color="textSecondary">
                          <Trans>Net Proceeds</Trans>
                        </Typography>
                        <Flex justifyContent="center">
                          <TooltipIcon>
                            <Trans>
                              The net proceeds include the asking price, minus
                              any associated creator fees (if the NFT has
                              royalty payments enabled).
                            </Trans>
                          </TooltipIcon>
                        </Flex>
                      </Flex>
                      <Typography variant="h5" fontWeight="bold">
                        <FormatLargeNumber
                          value={
                            new BigNumber(nftSaleInfo?.nftSellerNetAmount ?? 0)
                          }
                        />{' '}
                        {displayName}
                      </Typography>
                    </Flex>
                  )}
                </>
              )}
              {imported && isValid && (
                <Flex flexDirection="column" gap={2}>
                  <Divider />
                  <Flex flexDirection="column" gap={1}>
                    <Typography variant="body1" color="textSecondary">
                      <Trans>Network Fee (Optional)</Trans>
                    </Typography>
                    <Grid
                      direction="column"
                      xs={5}
                      sm={5}
                      md={5}
                      lg={5}
                      container
                    >
                      <Fee
                        id="filled-secondary"
                        variant="filled"
                        name="fee"
                        color="secondary"
                        label={<Trans>Fee</Trans>}
                        defaultValue={1}
                        disabled={isAccepting}
                      />
                    </Grid>
                  </Flex>
                </Flex>
              )}
              {imported && (
                <Flex
                  flexDirection="column"
                  flexGrow={1}
                  alignItems="flex-end"
                  justifyContent="flex-end"
                  style={{ paddingBottom: '1em' }}
                >
                  <Flex justifyContent="flex-end" gap={2}>
                    <Button
                      variant="outlined"
                      onClick={() => navigate(-1)}
                      disabled={isAccepting}
                    >
                      <Trans>Back</Trans>
                    </Button>
                    <ButtonLoading
                      variant="contained"
                      color="primary"
                      type="submit"
                      disabled={!isValid || isMissingRequestedAsset}
                      loading={isAccepting}
                    >
                      <Trans>Accept Offer</Trans>
                    </ButtonLoading>
                  </Flex>
                </Flex>
              )}
            </Flex>
            <NFTOfferPreview nftId={nftId} />
          </Flex>
        </Flex>
      </Flex>
    </Form>
  );
}

/* ========================================================================== */
/*                              NFT Offer Viewer                              */
/* ========================================================================== */

type NFTOfferViewerProps = {
  tradeRecord?: OfferTradeRecord;
  offerData?: string;
  offerSummary?: OfferSummaryRecord;
  offerFilePath?: string;
  imported?: boolean;
};

export default function NFTOfferViewer(props: NFTOfferViewerProps) {
  const {
    tradeRecord,
    offerData,
    offerSummary,
    offerFilePath,
    imported,
    ...rest
  } = props;

  return (
    <Grid container>
      <Flex flexDirection="column" flexGrow={1} gap={3}>
        <Flex>
          <Back variant="h5">
            <OfferViewerTitle
              offerFilePath={offerFilePath}
              tradeRecord={tradeRecord}
            />
          </Back>
        </Flex>
        <NFTOfferDetails
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
