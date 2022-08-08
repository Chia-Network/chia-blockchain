import { WalletType } from '@chia/api';
import { t } from '@lingui/macro';
import type { ChipProps } from '@mui/material';
import type {
  OfferSummaryAssetInfo,
  OfferSummaryInfos,
  OfferSummaryRecord,
} from '@chia/api';
import {
  mojoToCAT,
  mojoToChia,
  mojoToCATLocaleString,
  mojoToChiaLocaleString,
} from '@chia/core';
import NFTOfferExchangeType from './NFTOfferExchangeType';
import OfferState from './OfferState';
import OfferAsset from './OfferAsset';
import { AssetIdMapEntry } from '../../hooks/useAssetIdName';
import { launcherIdToNFTId } from '../../util/nfts';

let filenameCounter = 0;

export function summaryStringsForOffer(
  summary: OfferSummaryRecord,
  lookupByAssetId: (assetId: string) => AssetIdMapEntry | undefined,
  builder: (
    filename: string,
    args: [assetInfo: AssetIdMapEntry | undefined, amount: string],
  ) => string,
): [makerString: string, takerString: string] {
  const makerEntries: [string, string][] = Object.entries(summary.offered);
  const takerEntries: [string, string][] = Object.entries(summary.requested);
  const makerAssetInfoAndAmounts: [AssetIdMapEntry | undefined, string][] =
    makerEntries.map(([assetId, amount]) => [lookupByAssetId(assetId), amount]);
  const takerAssetInfoAndAmounts: [AssetIdMapEntry | undefined, string][] =
    takerEntries.map(([assetId, amount]) => [lookupByAssetId(assetId), amount]);

  const makerString = makerAssetInfoAndAmounts.reduce(builder, '');
  const takerString = takerAssetInfoAndAmounts.reduce(builder, '');

  return [makerString, takerString];
}

export function summaryStringsForNFTOffer(
  summary: OfferSummaryRecord,
  lookupByAssetId: (assetId: string) => AssetIdMapEntry | undefined,
  builder: (
    filename: string,
    args: [assetInfo: AssetIdMapEntry | undefined, amount: string],
  ) => string,
): [makerString: string, takerString: string] {
  // const makerAssetType = offerAssetTypeForAssetId
  // TODO: Remove 1:1 NFT <--> XCH assumption
  const makerEntry: [string, string] = Object.entries(summary.offered)[0];
  const takerEntry: [string, string] = Object.entries(summary.requested)[0];
  const makerAssetType = offerAssetTypeForAssetId(makerEntry[0], summary);
  const takerAssetType = offerAssetTypeForAssetId(takerEntry[0], summary);
  let makerString = '';
  let takerString = '';

  if (makerAssetType === OfferAsset.NFT) {
    makerString = `${makerEntry[1]}_${launcherIdToNFTId(makerEntry[0])}`;
  } else {
    const makerAssetInfoAndAmounts: [AssetIdMapEntry | undefined, string][] = [
      makerEntry,
    ].map(([assetId, amount]) => [lookupByAssetId(assetId), amount]);
    makerString = makerAssetInfoAndAmounts.reduce(builder, '');
  }

  if (takerAssetType === OfferAsset.NFT) {
    takerString = `${takerEntry[1]}_${launcherIdToNFTId(takerEntry[0])}`;
  } else {
    const takerAssetInfoAndAmounts: [AssetIdMapEntry | undefined, string][] = [
      takerEntry,
    ].map(([assetId, amount]) => [lookupByAssetId(assetId), amount]);
    takerString = takerAssetInfoAndAmounts.reduce(builder, '');
  }

  return [makerString, takerString];
}

export function suggestedFilenameForOffer(
  summary: OfferSummaryRecord,
  lookupByAssetId: (assetId: string) => AssetIdMapEntry | undefined,
): string {
  if (!summary) {
    const filename =
      filenameCounter === 0
        ? 'Untitled Offer.offer'
        : `Untitled Offer ${filenameCounter}.offer`;
    filenameCounter++;
    return filename;
  }

  function filenameBuilder(
    filename: string,
    args: [assetInfo: AssetIdMapEntry | undefined, amount: string],
  ): string {
    const [assetInfo, amount] = args;

    if (filename) {
      filename += '_';
    }

    if (assetInfo && amount !== undefined) {
      filename +=
        formatAmountForWalletType(amount, assetInfo.walletType) +
        assetInfo.displayName.replace(/\s/g, '').substring(0, 9);
    }

    return filename;
  }

  const [makerString, takerString] = offerContainsAssetOfType(
    summary,
    'singleton',
  )
    ? summaryStringsForNFTOffer(summary, lookupByAssetId, filenameBuilder)
    : summaryStringsForOffer(summary, lookupByAssetId, filenameBuilder);

  return `${makerString}_x_${takerString}.offer`;
}

export function shortSummaryForOffer(
  summary: OfferSummaryRecord,
  lookupByAssetId: (assetId: string) => AssetIdMapEntry | undefined,
): string {
  if (!summary) {
    return '';
  }

  function summaryBuilder(
    shortSummary: string,
    args: [assetInfo: AssetIdMapEntry | undefined, amount: string],
  ): string {
    const [assetInfo, amount] = args;

    if (shortSummary) {
      shortSummary += ', ';
    }

    if (assetInfo && amount !== undefined) {
      shortSummary +=
        formatAmountForWalletType(amount, assetInfo.walletType) +
        ' ' +
        assetInfo.displayName.replace(/\s/g, '');
    }

    return shortSummary;
  }

  const [makerString, takerString] = offerContainsAssetOfType(
    summary,
    'singleton',
  )
    ? summaryStringsForNFTOffer(summary, lookupByAssetId, summaryBuilder)
    : summaryStringsForOffer(summary, lookupByAssetId, summaryBuilder);

  return t`Offering: [${makerString}], Requesting: [${takerString}]`;
}

export function displayStringForOfferState(state: OfferState): string {
  switch (state) {
    case OfferState.PENDING_ACCEPT:
      return t`Pending Accept`;
    case OfferState.PENDING_CONFIRM:
      return t`Pending Confirm`;
    case OfferState.PENDING_CANCEL:
      return t`Pending Cancel`;
    case OfferState.CANCELLED:
      return t`Cancelled`;
    case OfferState.CONFIRMED:
      return t`Confirmed`;
    case OfferState.FAILED:
      return t`Failed`;
    default:
      return t`Unknown`;
  }
}

export function colorForOfferState(state: OfferState): ChipProps['color'] {
  switch (state) {
    case OfferState.PENDING_ACCEPT:
      return 'primary';
    case OfferState.PENDING_CONFIRM:
      return 'primary';
    case OfferState.PENDING_CANCEL:
      return 'primary';
    case OfferState.CANCELLED:
      return 'default';
    case OfferState.CONFIRMED:
      return 'secondary';
    case OfferState.FAILED:
      return 'error';
    default:
      return 'default';
  }
}

export function formatAmountForWalletType(
  amount: string | number,
  walletType: WalletType,
  locale?: string,
): string {
  if (walletType === WalletType.STANDARD_WALLET) {
    return mojoToChiaLocaleString(amount, locale);
  } else if (walletType === WalletType.CAT) {
    return mojoToCATLocaleString(amount, locale);
  }

  return amount.toString();
}

export function offerContainsAssetOfType(
  offerSummary: OfferSummaryRecord,
  assetType: string,
): boolean {
  const infos: OfferSummaryInfos = offerSummary.infos;
  const matchingAssetId: string | undefined = Object.keys(infos).find(
    (assetId) => {
      const info: OfferSummaryAssetInfo = infos[assetId];
      return info.type === assetType;
    },
  );

  return (
    !!matchingAssetId &&
    // Sanity check that the assetId is actually being offered/requested
    (Object.keys(offerSummary.offered).includes(matchingAssetId) ||
      Object.keys(offerSummary.requested).includes(matchingAssetId))
  );
}

export function offerAssetTypeForAssetId(
  assetId: string,
  offerSummary: OfferSummaryRecord,
): OfferAsset | undefined {
  let assetType: OfferAsset | undefined;

  if (['xch', 'txch'].includes(assetId)) {
    assetType = OfferAsset.CHIA;
  } else {
    const infos: OfferSummaryInfos = offerSummary.infos;
    const info: OfferSummaryAssetInfo = infos[assetId];

    if (info) {
      switch (info.type.toLowerCase()) {
        case 'cat':
          assetType = OfferAsset.TOKEN;
          break;
        case 'singleton':
          assetType = OfferAsset.NFT;
          break;
        default:
          break;
      }
    }
  }

  return assetType;
}

export function offerAssetIdForAssetType(
  assetType: OfferAsset,
  offerSummary: OfferSummaryRecord,
): string | undefined {
  if (assetType === OfferAsset.CHIA) {
    return 'xch';
  }

  const assetId = Object.keys(offerSummary.infos).find(
    (assetId) => offerAssetTypeForAssetId(assetId, offerSummary) === assetType,
  );

  return assetId;
}

export function offerAssetAmountForAssetId(
  assetId: string,
  offerSummary: OfferSummaryRecord,
): number | undefined {
  let amount = Object.keys(offerSummary.offered).includes(assetId)
    ? offerSummary.offered[assetId]
    : undefined;

  if (amount === undefined) {
    amount = Object.keys(offerSummary.requested).includes(assetId)
      ? offerSummary.requested[assetId]
      : undefined;
  }
  return amount;
}

/* ========================================================================== */

export function determineNFTOfferExchangeType(
  summary: OfferSummaryRecord,
): NFTOfferExchangeType | undefined {
  const nftOffered = Object.keys(summary.offered).find(
    (assetId) => offerAssetTypeForAssetId(assetId, summary) === OfferAsset.NFT,
  );
  const nftRequested = Object.keys(summary.requested).find(
    (assetId) => offerAssetTypeForAssetId(assetId, summary) === OfferAsset.NFT,
  );

  if (nftOffered === nftRequested) {
    // NFT for NFT currently unsupported. Non-NFT for non-NFT is a separate type of offer...
    return undefined;
  }

  return nftOffered
    ? NFTOfferExchangeType.NFTForToken
    : NFTOfferExchangeType.TokenForNFT;
}

/* ========================================================================== */

export type GetNFTPriceWithoutRoyaltiesResult = {
  amount: number;
  assetId: string;
  assetType: OfferAsset;
};

export function getNFTPriceWithoutRoyalties(
  summary: OfferSummaryRecord,
): GetNFTPriceWithoutRoyaltiesResult | undefined {
  for (const assetType of [OfferAsset.TOKEN, OfferAsset.CHIA]) {
    const assetId = offerAssetIdForAssetType(assetType, summary);
    if (assetId) {
      const amountInMojos = offerAssetAmountForAssetId(assetId, summary);
      if (amountInMojos) {
        const amountInTokens =
          assetType === OfferAsset.CHIA
            ? mojoToChia(amountInMojos)
            : mojoToCAT(amountInMojos);
        return { amount: amountInTokens.toNumber(), assetId, assetType };
      }
    }
  }

  return undefined;
}

/* ========================================================================== */

export type CalculateNFTRoyaltiesResult = {
  royaltyAmount: number;
  royaltyAmountString: string;
  nftSellerNetAmount: number;
  totalAmount: number;
  totalAmountString: string;
};

export function calculateNFTRoyalties(
  amount: number,
  makerFee: number,
  royaltyPercentage: number,
  exchangeType: NFTOfferExchangeType,
): CalculateNFTRoyaltiesResult {
  const royaltyAmount: number = royaltyPercentage
    ? (royaltyPercentage / 100) * amount
    : 0;
  const royaltyAmountString: string = formatAmount(royaltyAmount);
  const nftSellerNetAmount: number = amount;
  // : parseFloat(
  //     (amount - parseFloat(royaltyAmountString) - makerFee).toFixed(12),
  //   );
  const totalAmount: number =
    exchangeType === NFTOfferExchangeType.NFTForToken
      ? amount + royaltyAmount
      : amount + makerFee + royaltyAmount;
  const totalAmountString: string = formatAmount(totalAmount);

  return {
    royaltyAmount,
    royaltyAmountString,
    nftSellerNetAmount,
    totalAmount,
    totalAmountString,
  };
}

export function formatAmount(amount: number): string {
  let s = amount.toFixed(12).replace(/0+$/, '');
  if (s.endsWith('.')) {
    s = s.slice(0, -1);
  }
  return s;
}
