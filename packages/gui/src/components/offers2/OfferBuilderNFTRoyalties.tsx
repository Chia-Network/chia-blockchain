import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import type { NFTInfo } from '@chia/api';
import { useGetCatListQuery } from '@chia/api-react';
import {
  Flex,
  TooltipIcon,
  Loading,
  useCurrencyCode,
  mojoToChia,
  mojoToCAT,
  Truncate,
  FormatLargeNumber,
} from '@chia/core';
import { Typography } from '@mui/material';
import useOfferBuilderContext from '../../hooks/useOfferBuilderContext';

export type OfferBuilderNFTRoyaltiesProps = {
  nft?: NFTInfo;
};

export default function OfferBuilderNFTRoyalties(
  props: OfferBuilderNFTRoyaltiesProps,
) {
  const { nft } = props;

  const { royalties: allRoyalties } = useOfferBuilderContext();
  const { data: catList, isLoading: isLoadingCATs } = useGetCatListQuery();
  const currencyCode = useCurrencyCode();

  const isLoading = !allRoyalties || isLoadingCATs;
  const royalties = allRoyalties?.[nft.$nftId];

  const hasRoyalties = royalties?.length ?? 0 > 0;

  const rows = useMemo(() => {
    return royalties?.map((royalty) => {
      const { address, amount, asset } = royalty;
      const assetLowerCase = asset.toLowerCase();

      if (
        assetLowerCase === 'xch' ||
        assetLowerCase === currencyCode.toUpperCase()
      ) {
        return {
          address,
          amount: mojoToChia(amount),
          symbol: currencyCode.toUpperCase(),
        };
      }

      const cat = catList?.find((cat) => cat.assetId === asset);
      if (cat) {
        return {
          address,
          amount: mojoToCAT(amount),
          symbol: cat.symbol,
        };
      }

      return {
        address,
        amount: mojoToCAT(amount),
        symbol: <Truncate>{address}</Truncate>,
      };
    });
  }, [royalties, catList, currencyCode]);

  return (
    <Flex flexDirection="column" flexGrow={1} gap={2}>
      <Flex flexDirection="row" alignItems="center">
        <Typography variant="h6">Royalties</Typography>
        &nbsp;
        <TooltipIcon>
          <Trans>
            Royalties are built into the NFT, so they will automatically be
            accounted for when the offer is created/accepted.
          </Trans>
        </TooltipIcon>
      </Flex>
      {isLoading ? (
        <Loading center />
      ) : hasRoyalties ? (
        <Flex flexDirection="column" gap={0.5}>
          {rows?.map(({ address, amount, symbol }) => (
            <Flex
              key={`${address}-${amount}`}
              flexDirection="row"
              gap={1}
              alignItems="baseline"
            >
              <Typography variant="body2" color="textSecondary">
                <FormatLargeNumber value={amount} />
              </Typography>
              <Typography variant="body2" color="textSecondary" noWrap>
                {symbol}
              </Typography>
            </Flex>
          ))}
        </Flex>
      ) : (
        <Typography variant="body1" color="textSecondary">
          <Trans>NFT has no royalties</Trans>
        </Typography>
      )}
    </Flex>
  );
}
