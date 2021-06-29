import { useMemo } from 'react';
import seedrandom from 'seedrandom';
import { uniqueNamesGenerator, adjectives, colors, animals } from 'unique-names-generator';
import type PlotNFTExternal from '../types/PlotNFTExternal';
import type PlotNFT from '../types/PlotNFT';

export default function usePlotNFTName(nft: PlotNFT | PlotNFTExternal): string {
  const name = useMemo(() => {
    const {
      pool_state: {
        p2_singleton_puzzle_hash,
      },
    } = nft;

    const generator = seedrandom(p2_singleton_puzzle_hash);
    const seed = generator.int32();

    return uniqueNamesGenerator({
        dictionaries: [colors, animals, adjectives], // colors can be omitted here as not used
        length: 2,
        seed,
        separator: ' ',
        style: 'capital',
      });
  }, [nft]);

  return name;
}
