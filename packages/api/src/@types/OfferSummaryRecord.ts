export type OfferSummaryAssetAndAmount = {
  [key: string]: string;
};

export type OfferSummaryAssetInfo = {
  type: 'CAT' | 'NFT';
};

export type OfferSummaryCATInfo = OfferSummaryAssetInfo & {
  tail: string;
};

export type OfferSummaryNFTInfo = OfferSummaryAssetInfo & {
  launcherId: string;
};

export type OfferSummaryInfos = {
  [key: string]: OfferSummaryCATInfo | OfferSummaryNFTInfo;
};

type OfferSummaryRecord = {
  offered: OfferSummaryAssetAndAmount;
  requested: OfferSummaryAssetAndAmount;
  infos: OfferSummaryInfos;
  fees: number;
};

export default OfferSummaryRecord;
