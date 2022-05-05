import React, { useState, useMemo } from 'react';
import { Flex, LayoutDashboardSub, Loading, useTrans } from '@chia/core';
import { defineMessage } from '@lingui/macro';
import type { NFTInfo, Wallet } from '@chia/api';
import { useGetNFTWallets } from '@chia/api-react';
import { Grid } from '@mui/material';
import NFTGallerySidebar from './NFTGallerySidebar';
import NFTCard from '../NFTCard';
import Search from './NFTGallerySearch';
import NFTContextualActions from '../NFTContextualActions';
import type NFTSelection from '../../../types/NFTSelection';
import useFetchNFTs from '../../../hooks/useFetchNFTs';

export default function NFTGallery() {
  const { wallets: nftWallets, isLoading: isLoadingWallets } =
    useGetNFTWallets();
  const { nfts, isLoading: isLoadingNFTs } = useFetchNFTs(
    nftWallets.map((wallet: Wallet) => wallet.id),
  );
  const isLoading = isLoadingWallets || isLoadingNFTs;
  const [search, setSearch] = useState('');
  const t = useTrans();
  const [selection, setSelection] = useState<NFTSelection>({
    items: [],
  });

  const filteredData = useMemo(() => {
    if (!nfts || !search) {
      return nfts;
    }

    return nfts.filter(({ metadata = {} }) => {
      const { name = 'Test' } = metadata;
      return name.toLowerCase().includes(search.toLowerCase());
    });
  }, [search, nfts]);

  function handleSelect(nft: NFTInfo, selected: boolean) {
    setSelection((currentSelection) => {
      const { items } = currentSelection;

      return {
        items: selected
          ? [...items, nft]
          : items.filter((item) => item.id !== nft.id),
      };
    });
  }

  if (isLoading) {
    return <Loading center />;
  }

  return (
    <LayoutDashboardSub sidebar={<NFTGallerySidebar />}>
      <Flex flexDirection="column" gap={2}>
        <Flex justifyContent="space-between" alignItems="Center">
          <Search
            onChange={setSearch}
            value={search}
            placeholder={t(defineMessage({ message: `Search...` }))}
          />
          <NFTContextualActions selection={selection} />
        </Flex>

        <Grid spacing={2} alignItems="stretch" container>
          {filteredData?.map((nft: NFTInfo) => (
            <Grid xs={12} md={6} lg={4} xl={3} key={nft.id} item>
              <NFTCard
                nft={nft}
                onSelect={(selected) => handleSelect(nft, selected)}
                selected={selection.items.some((item) => item.id === nft.id)}
              />
            </Grid>
          ))}
        </Grid>
      </Flex>
    </LayoutDashboardSub>
  );
}
