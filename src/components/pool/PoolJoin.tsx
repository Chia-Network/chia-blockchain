import type { ReactNode } from 'react';
import useJoinPool from '../../hooks/useJoinPool';
import type PlotNFT from '../../types/PlotNFT';

type Props = {
  nft: PlotNFT;
  children: (joinPool) => JSX.Element,
};

export default function PoolJoin(props: Props) {
  const { nft, children } = props;

  const joinPool = useJoinPool(nft);

  return children(joinPool);
}
