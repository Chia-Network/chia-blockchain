type NFTInfo = {
  walletId: number;
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
};

export default NFTInfo;
