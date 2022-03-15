
type OfferSummaryAssetAndAmount = {
  [key: string]: string;
};

type OfferSummaryRecord = {
  offered: OfferSummaryAssetAndAmount;
  requested: OfferSummaryAssetAndAmount;
  fees: number;
};

export default OfferSummaryRecord;
