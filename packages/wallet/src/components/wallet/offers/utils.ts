import WalletType from '../../../constants/WalletType';
import {
  mojo_to_chia_string,
  mojo_to_colouredcoin_string,
} from '../../../util/chia';
import OfferState from './OfferState';
import OfferSummaryRecord from '../../../types/OfferSummaryRecord';
import { AssetIdMapEntry } from '../../../hooks/useAssetIdName';

var filenameCounter = 0;

export function suggestedFilenameForOffer(summary: OfferSummaryRecord, lookupByAssetId: (assetId: string) => AssetIdMapEntry | undefined): string {
  if (!summary) {
    const filename = filenameCounter === 0 ? 'Untitled Offer.offer' : `Untitled Offer ${filenameCounter}.offer`;
    filenameCounter++;
    return filename;
  }

  const makerEntries: [string, string][] = Object.entries(summary.offered);
  const takerEntries: [string, string][] = Object.entries(summary.requested);
  const makerAssetInfoAndAmounts: [AssetIdMapEntry | undefined, string][] = makerEntries.map(([assetId, amount]) => [lookupByAssetId(assetId), amount]);
  const takerAssetInfoAndAmounts: [AssetIdMapEntry | undefined, string][] = takerEntries.map(([assetId, amount]) => [lookupByAssetId(assetId), amount]);

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

  const makerString = makerAssetInfoAndAmounts.reduce(filenameBuilder, '');
  const takerString = takerAssetInfoAndAmounts.reduce(filenameBuilder, '');

  return `${makerString}_x_${takerString}.offer`;
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

type OfferStateColor =
| 'initial'
| 'inherit'
| 'primary'
| 'secondary'
| 'textPrimary'
| 'textSecondary'
| 'error';

export function colorForOfferState(state: OfferState): OfferStateColor {
  switch (state) {
    case OfferState.PENDING_ACCEPT:
      return 'primary';
    case OfferState.PENDING_CONFIRM:
      return 'primary';
    case OfferState.PENDING_CANCEL:
      return 'primary';
    case OfferState.CANCELLED:
      return 'inherit';
    case OfferState.CONFIRMED:
      return 'secondary';
    case OfferState.FAILED:
      return 'error';
    default:
      return 'inherit';
  }
}

export function formatAmountForWalletType(amount: string | number, walletType: WalletType): string {
  let amountString = '';
  if (walletType === WalletType.STANDARD_WALLET) {
    amountString = mojo_to_chia_string(amount);
  }
  else if (walletType === WalletType.CAT) {
    amountString = mojo_to_colouredcoin_string(amount);
  }
  else {
    amountString = `${amount}`;
  }
  return amountString;
}
