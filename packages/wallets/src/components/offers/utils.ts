import { WalletType } from '@chia/api';
import type { ChipProps } from '@mui/material';
import type { OfferSummaryRecord } from '@chia/api';
import {
  mojoToChiaLocaleString,
  mojoToCATLocaleString,
} from '@chia/core';
import OfferState from './OfferState';
import { AssetIdMapEntry } from '../../hooks/useAssetIdName';

let filenameCounter = 0;

export function summaryStringsForOffer(
  summary: OfferSummaryRecord,
  lookupByAssetId: (assetId: string) => AssetIdMapEntry | undefined,
  builder: (filename: string, args: [assetInfo: AssetIdMapEntry | undefined, amount: string]) => string): [makerString: string, takerString: string] {
    const makerEntries: [string, string][] = Object.entries(summary.offered);
    const takerEntries: [string, string][] = Object.entries(summary.requested);
    const makerAssetInfoAndAmounts: [AssetIdMapEntry | undefined, string][] = makerEntries.map(([assetId, amount]) => [lookupByAssetId(assetId), amount]);
    const takerAssetInfoAndAmounts: [AssetIdMapEntry | undefined, string][] = takerEntries.map(([assetId, amount]) => [lookupByAssetId(assetId), amount]);

    const makerString = makerAssetInfoAndAmounts.reduce(builder, '');
    const takerString = takerAssetInfoAndAmounts.reduce(builder, '');

    return [makerString, takerString];
}

export function suggestedFilenameForOffer(summary: OfferSummaryRecord, lookupByAssetId: (assetId: string) => AssetIdMapEntry | undefined): string {
  if (!summary) {
    const filename = filenameCounter === 0 ? 'Untitled Offer.offer' : `Untitled Offer ${filenameCounter}.offer`;
    filenameCounter++;
    return filename;
  }

  function filenameBuilder(filename: string, args: [assetInfo: AssetIdMapEntry | undefined, amount: string]): string {
    const [assetInfo, amount] = args;

    if (filename) {
      filename += '_';
    }

    if (assetInfo && amount !== undefined) {
      filename += formatAmountForWalletType(amount, assetInfo.walletType) + assetInfo.displayName.replace(/\s/g, '').substring(0, 9);
    }

    return filename;
  }

  const [makerString, takerString] = summaryStringsForOffer(summary, lookupByAssetId, filenameBuilder);

  return `${makerString}_x_${takerString}.offer`;
}

export function shortSummaryForOffer(summary: OfferSummaryRecord, lookupByAssetId: (assetId: string) => AssetIdMapEntry | undefined): string {
  if (!summary) {
    return '';
  }

  function summaryBuilder(shortSummary: string, args: [assetInfo: AssetIdMapEntry | undefined, amount: string]): string {
    const [assetInfo, amount] = args;

    if (shortSummary) {
      shortSummary += ', ';
    }

    if (assetInfo && amount !== undefined) {
      shortSummary += formatAmountForWalletType(amount, assetInfo.walletType) + ' ' + assetInfo.displayName.replace(/\s/g, '');
    }

    return shortSummary;
  }

  const [makerString, takerString] = summaryStringsForOffer(summary, lookupByAssetId, summaryBuilder);

  return `Offering: [${makerString}], Requesting: [${takerString}]`;
}

export function displayStringForOfferState(state: OfferState): string {
  switch (state) {
    case OfferState.PENDING_ACCEPT:
      return 'Pending Accept';
    case OfferState.PENDING_CONFIRM:
      return 'Pending Confirm';
    case OfferState.PENDING_CANCEL:
      return 'Pending Cancel';
    case OfferState.CANCELLED:
      return 'Cancelled';
    case OfferState.CONFIRMED:
      return 'Confirmed';
    case OfferState.FAILED:
      return 'Failed';
    default:
      return 'Unknown';
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

export function formatAmountForWalletType(amount: string | number, walletType: WalletType, locale?: string): string {
  if (walletType === WalletType.STANDARD_WALLET) {
    return mojoToChiaLocaleString(amount, locale);
  } else if (walletType === WalletType.CAT) {
    return mojoToCATLocaleString(amount, locale);
  }

  return amount.toString();
}
