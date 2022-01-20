
type OfferSummaryAssetAndAmount = {
  [key: string]: string;
};

type OfferSummaryRecord = {
  offered: OfferSummaryAssetAndAmount;
  requested: OfferSummaryAssetAndAmount;
};

export default OfferSummaryRecord;
