import React, { useState, useMemo } from 'react';
import { Flex, LayoutDashboardSub, Loading, toBech32m, useTrans } from '@chia/core';
import { defineMessage } from '@lingui/macro';
import type { NFT } from '@chia/api';
import { useGetCurrentNFTsQuery } from '@chia/api-react';
import { Grid } from '@mui/material';
import NFTGallerySidebar from './NFTGallerySidebar';
import NFTCard from '../NFTCard';
import Search from './NFTGallerySearch';
import NFTContextualActions from '../NFTContextualActions';
import type NFTSelection from '../../../types/NFTSelection';

export default function NFTGallery() {
  const { isLoading, data } = useGetCurrentNFTsQuery();
  const [search, setSearch] = useState('');
  const t = useTrans();
  const [selection, setSelection] = useState<NFTSelection>({
    items: [],
  });

  const transformedData = useMemo(() => {
    if (!data) {
      return data;
    }

    return data.map((nft: NFT) => {
      return { ...nft, id: toBech32m(nft.id, 'nft') };
    });
  }, [data]);

  const filteredData = useMemo(() => {
    if (!transformedData || !search) {
      return transformedData;
    }

    return transformedData.filter(({ metadata = {} }) => {
      const { name = 'Test' } = metadata;
      return name.toLowerCase().includes(search.toLowerCase());
    });
  }, [search, transformedData]);

  function handleSelect(nft: NFT, selected: boolean) {
    setSelection((currentSelection) => {
      const { items } = currentSelection;

      return {
        items: selected ? [...items, nft] : items.filter((item) => item.id !== nft.id),
      };
    });
  }


  if (isLoading) {
    return (
      <Loading center />
    );
  }

  return (
    <LayoutDashboardSub sidebar={<NFTGallerySidebar />}>
      <Flex flexDirection="column" gap={2}>
        <Flex justifyContent="space-between" alignItems="Center">
          <Search onChange={setSearch} value={search} placeholder={t(defineMessage({ message: `Search...` }))} />
          <NFTContextualActions selection={selection} />
        </Flex>

        <Grid spacing={2} alignItems="stretch" container>
          {filteredData?.map((nft) => (
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
