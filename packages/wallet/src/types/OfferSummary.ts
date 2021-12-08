
type OfferSummaryAssetAndAmount = {
  [key: string]: string;
};

type OfferSummary = {
  offered: OfferSummaryAssetAndAmount;
  requested: OfferSummaryAssetAndAmount;
};

export default OfferSummary;
