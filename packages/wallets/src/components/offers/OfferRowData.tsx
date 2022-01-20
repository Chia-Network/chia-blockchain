import { type WalletType } from '@chia/api';

type OfferRowData = {
  amount: number | string;
  assetWalletId: number | undefined; // undefined if no selection made
  walletType: WalletType;
};

export default OfferRowData;
