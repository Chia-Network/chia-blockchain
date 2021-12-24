import type WalletType from '../../../constants/WalletType';

type OfferRowData = {
  amount: number | string;
  assetWalletId: number | undefined; // undefined if no selection made
  walletType: WalletType;
};

export default OfferRowData;
