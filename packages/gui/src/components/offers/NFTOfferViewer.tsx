import React, { useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate } from 'react-router-dom';
import { Plural, Trans } from '@lingui/macro';
import {
  useCheckOfferValidityMutation,
  useGetNFTWallets,
} from '@chia/api-react';
import type { NFTInfo, Wallet } from '@chia/api';
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
  TooltipIcon,
  useShowError,
} from '@chia/core';
import { Divider, Grid, Typography } from '@mui/material';
import useAcceptOfferHook from '../../hooks/useAcceptOfferHook';
import useAssetIdName from '../../hooks/useAssetIdName';
import useFetchNFTs from '../../hooks/useFetchNFTs';
import { launcherIdToNFTId } from '../../util/nfts';
import { offerAssetTypeForAssetId } from './utils';
import OfferAsset from './OfferAsset';
import OfferHeader from './OfferHeader';
import OfferState from './OfferState';
import { OfferSummaryNFTRow, OfferSummaryTokenRow } from './OfferSummaryRow';
import OfferViewerTitle from './OfferViewerTitle';
import NFTOfferPreview from './NFTOfferPreview';
import styled from 'styled-components';

/* ========================================================================== */

const StyledWarningText = styled(Typography)`
  color: ${StateColor.WARNING};
`;

/* ========================================================================== */

type NFTOfferSummaryRowProps = {
  title: React.ReactElement | string;
  summaryKey: string;
  summary: any;
  unknownAssets?: string[];
};

function NFTOfferSummaryRow(props: NFTOfferSummaryRowProps) {
  const { title, summaryKey, summary, unknownAssets } = props;
  const summaryData: { [key: string]: number } = summary[summaryKey];
  const summaryInfo = summary.infos;
  const assetIdsToTypes: { [key: string]: OfferAsset | undefined }[] =
    useMemo(() => {
      return Object.keys(summaryData).map((key) => {
        const infoDict = summaryInfo[key];
        let assetType: OfferAsset | undefined;

        if (['xch', 'txch'].includes(key.toLowerCase())) {
          assetType = OfferAsset.CHIA;
        } else if (!!infoDict?.type) {
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

    console.log('assetId and amount:');
    console.log(assetId);
    console.log(summaryData[assetId]);
    switch (assetType) {
      case undefined:
        return null;
      case OfferAsset.CHIA: // fall-through
      case OfferAsset.TOKEN:
        return (
          <OfferSummaryTokenRow
            assetId={assetId}
            amount={summaryData[assetId]}
          />
        );
      case OfferAsset.NFT:
        return (
          <OfferSummaryNFTRow
            launcherId={assetId}
            amount={summaryData[assetId]}
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
        {rows.map((row, index) => (
          <div key={index}>{row}</div>
        ))}
      </Flex>
      {unknownAssets !== undefined && unknownAssets.length > 0 && (
        <Flex flexDirection="row" gap={1}>
          <StyledWarningText variant="caption">
            Offer cannot be accepted because you don't possess the requested
            assets
          </StyledWarningText>
        </Flex>
      )}
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
  makerTitle: React.ReactElement | string;
  takerTitle: React.ReactElement | string;
  setIsMissingRequestedAsset?: (isMissing: boolean) => void;
};

function NFTOfferSummary(props: NFTOfferSummaryProps) {
  const {
    isMyOffer,
    imported,
    summary,
    makerTitle,
    takerTitle,
    setIsMissingRequestedAsset,
  } = props;
  const { lookupByAssetId } = useAssetIdName();
  const { wallets: nftWallets, isLoading: isLoadingWallets } =
    useGetNFTWallets();
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
        ([assetId, _]) =>
          offerAssetTypeForAssetId(assetId, summary) !== OfferAsset.NFT &&
          lookupByAssetId(assetId) === undefined,
      )
      .map(([assetId, _]) => assetId);

    const makerUnknownAssets = takerEntries
      .filter(([assetId, _]) => {
        const assetType = offerAssetTypeForAssetId(assetId, summary);
        if (assetType === OfferAsset.NFT) {
          return (
            nfts.find(
              (nft) => nft.launcherId.toLowerCase() === assetId.toLowerCase(),
            ) === undefined
          );
        }
        return lookupByAssetId(assetId) === undefined;
      })
      .map(([assetId, _]) => assetId);

    return [takerUnknownAssets, makerUnknownAssets];
  }, [summary, isLoadingNFTs]);
  const makerSummary: React.ReactElement = (
    <NFTOfferSummaryRow
      title={makerTitle}
      summaryKey="offered"
      summary={summary}
      unknownAssets={isMyOffer ? undefined : takerUnknownAssets}
    />
  );
  const takerSummary: React.ReactElement = (
    <NFTOfferSummaryRow
      title={takerTitle}
      summaryKey="requested"
      summary={summary}
      unknownAssets={isMyOffer ? undefined : makerUnknownAssets}
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
    <>
      <Typography variant="h6" style={{ fontWeight: 'bold' }}>
        <Trans>Purchase Summary</Trans>
      </Typography>
      {summaries.map((summary, index) => (
        <Flex flexDirection="column" key={index} gap={3}>
          {summary}
          {index !== summaries.length - 1 && <Divider />}
        </Flex>
      ))}
      {makerFee > 0 && (
        <Flex flexDirection="column" gap={2}>
          <Divider />
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
                  This offer has a fee included to help expedite the transaction
                  when the offer is accepted. You may specify an additional fee
                  if you feel that the included fee is too small.
                </Trans>
              ) : (
                <Trans>
                  This offer has a fee included to help expedite the transaction
                  when the offer is accepted.
                </Trans>
              )}
            </TooltipIcon>
          </Flex>
        </Flex>
      )}
    </>
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
  const isMyOffer = !!tradeRecord?.isMyOffer;
  const showError = useShowError();
  const methods = useForm({ defaultValues: { fee: '' } });
  const navigate = useNavigate();
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
          style={{
            border: '1px solid #E0E0E0',
            boxSizing: 'border-box',
            borderRadius: '8px',
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
                makerTitle={
                  <Typography variant="body1">
                    <Trans>You will receive</Trans>
                  </Typography>
                }
                takerTitle={
                  <Typography variant="body1">
                    <Trans>In exchange for</Trans>
                  </Typography>
                }
                setIsMissingRequestedAsset={(isMissing: boolean) =>
                  setIsMissingRequestedAsset(isMissing)
                }
              />
              <Divider />
              {imported && (
                <Flex
                  flexDirection="column"
                  flexGrow={1}
                  justifyContent="space-between"
                  gap={3}
                >
                  {isValid && (
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
                  )}
                  <Flex
                    flexDirection="column"
                    flexGrow={1}
                    alignItems="flex-end"
                    justifyContent="flex-end"
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
