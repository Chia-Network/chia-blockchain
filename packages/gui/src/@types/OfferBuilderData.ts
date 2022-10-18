type OfferBuilderData = {
  offered: {
    xch: {
      amount: string;
    }[];
    tokens: {
      amount: string;
      assetId: string;
    }[];
    nfts: {
      nftId: string;
    }[];
    fee: {
      amount: string;
    }[];
  };
  requested: {
    xch: {
      amount: string;
    }[];
    tokens: {
      amount: string;
      assetId: string;
    }[];
    nfts: {
      nftId: string;
    }[];
    fee: {
      amount: string;
    }[];
  };
};

export default OfferBuilderData;
