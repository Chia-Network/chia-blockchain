import { uniq } from 'lodash';
import React, { ReactNode, useMemo } from 'react';
import { useWatch } from 'react-hook-form';
import {
  fungibleAssetFromAssetIdAndAmount,
  royaltyAssetFromNFTInfo,
} from '@chia/api';
import type { CalculateRoyaltiesRequest, NFTInfo } from '@chia/api';
import {
  useCalculateRoyaltiesForNFTsQuery,
  useGetNFTsByNFTIDsQuery,
} from '@chia/api-react';
import { catToMojo, chiaToMojo } from '@chia/core';
import OfferBuilderContext from './OfferBuilderContext';

export type OfferBuilderProviderProps = {
  children: ReactNode;
  readOnly?: boolean;
  isMyOffer?: boolean;
};

export default function OfferBuilderProvider(props: OfferBuilderProviderProps) {
  const { children, readOnly = false, isMyOffer = false } = props;
  let royaltyNFTsSelector = undefined;
  let fungibleXCHSelector = undefined;
  let fungibleTokenSelector = undefined;

  if (readOnly && isMyOffer) {
    royaltyNFTsSelector = 'requested.nfts';
    fungibleXCHSelector = 'offered.xch';
    fungibleTokenSelector = 'offered.tokens';
  } else {
    royaltyNFTsSelector = 'offered.nfts';
    fungibleXCHSelector = 'requested.xch';
    fungibleTokenSelector = 'requested.tokens';
  }

  const offeredTokens = useWatch({
    name: 'offered.tokens',
  });

  const requestedTokens = useWatch({
    name: 'requested.tokens',
  });

  const royaltyNFTIds = useWatch({
    name: royaltyNFTsSelector,
  })?.map(({ nftId }) => nftId);

  const fungibleXCH = useWatch({
    name: fungibleXCHSelector,
  });

  const fungibleTokens = useWatch({
    name: fungibleTokenSelector,
  });

  const { data: royaltyNFTs } = useGetNFTsByNFTIDsQuery(
    { nftIds: royaltyNFTIds },
    { skip: royaltyNFTIds.length === 0 },
  );

  const royaltyAssets = (royaltyNFTs ?? [])
    .filter((nft: NFTInfo) => nft?.royaltyPercentage > 0)
    .map((nft: NFTInfo) => royaltyAssetFromNFTInfo(nft));

  const fungibleAssets = [
    ...(fungibleXCH ?? [])
      .filter(({ amount }) => amount > 0)
      .map(({ amount }) =>
        fungibleAssetFromAssetIdAndAmount('xch', chiaToMojo(amount)),
      ),
    ...(fungibleTokens ?? [])
      .filter(({ assetId, amount }) => assetId?.length > 0 && amount > 0)
      .map(({ amount, assetId }) =>
        fungibleAssetFromAssetIdAndAmount(assetId, catToMojo(amount)),
      ),
  ];

  const request: CalculateRoyaltiesRequest = {
    royaltyAssets,
    fungibleAssets,
  };

  const { data: royalties } = useCalculateRoyaltiesForNFTsQuery(request, {
    skip:
      request.royaltyAssets.length === 0 || request.fungibleAssets.length === 0,
  });

  const usedAssetIds = useMemo(() => {
    const used: string[] = [];

    offeredTokens?.forEach(({ assetId }: { assetId: string }) => {
      if (assetId) {
        used.push(assetId);
      }
    });
    requestedTokens?.forEach(({ assetId }: { assetId: string }) => {
      if (assetId) {
        used.push(assetId);
      }
    });

    return uniq(used);
  }, [offeredTokens, requestedTokens]);

  const context = useMemo(
    () => ({
      readOnly,
      usedAssetIds,
      royalties,
    }),
    [readOnly, usedAssetIds, royalties],
  );

  return (
    <OfferBuilderContext.Provider value={context}>
      {children}
    </OfferBuilderContext.Provider>
  );
}
