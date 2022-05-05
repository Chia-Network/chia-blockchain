type NFTInfo = {
  launcherId: string;
  nftCoinId: string;
  didOwner: string;
  royalty: number;
  dataUris: string[];
  dataHash: string;
  metadataUris: string[];
  metadataHash: string;
  licenseUris: string[];
  licenseHash: string;
  version: string;
  editionCount: number;

  // Properties added by the frontend
  walletId: number;
  id: string; // bech32m-encoding of the launcherId e.g. nft1eryfv3va6lftjslhq3jhyx30dk8wtsfd8epseuq3rnlf2tavpjmsq0ljcv
};

export default NFTInfo;
