import useAbsorbRewards from '../../hooks/useAbsorbRewards';
import type PlotNFT from '../../types/PlotNFT';

type Props = {
  nft: PlotNFT;
  children: (absorbRewards: Function) => JSX.Element,
};

export default function PlotNFTAbsorbRewards(props: Props) {
  const { nft, children } = props;

  const absorbRewards = useAbsorbRewards(nft);

  return children(absorbRewards);
}
