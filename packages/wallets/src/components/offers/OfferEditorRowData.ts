import type BigNumber from 'bignumber.js';
import OfferRowData from './OfferRowData';

type OfferEditorRowData = OfferRowData & {
  spendableBalance: BigNumber;
  spendableBalanceString?: string;
};

export default OfferEditorRowData;
