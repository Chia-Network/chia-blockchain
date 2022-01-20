import OfferRowData from './OfferRowData';

type OfferEditorRowData = OfferRowData & {
  spendableBalance: number;
  spendableBalanceString?: string;
};

export default OfferEditorRowData;
