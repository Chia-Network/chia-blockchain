import WalletType from '../../../constants/WalletType';
import {
  mojo_to_chia_string,
  mojo_to_colouredcoin_string,
} from '../../../util/chia';
import OfferState from './OfferState';

var filenameCounter = 0;

export function suggestedFilenameForOffer(): string {
  const filename = filenameCounter === 0 ? 'Untitled Offer.offer' : `Untitled Offer ${filenameCounter}.offer`;
  filenameCounter++;
  return filename;
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
