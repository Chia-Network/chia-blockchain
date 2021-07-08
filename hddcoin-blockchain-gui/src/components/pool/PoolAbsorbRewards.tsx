import { useHistory } from 'react-router';
import type PlotNFT from '../../types/PlotNFT';
import usePlotNFTDetails from '../../hooks/usePlotNFTDetails';

type Props = {
  nft: PlotNFT;
  children: (data: {
    absorb: () => Promise<void>;
    disabled: boolean;
  }) => JSX.Element;
};

export default function PoolAbsorbRewards(props: Props) {
  const {
    children,
    nft,
    nft: {
      pool_state: { p2_singleton_puzzle_hash },
    },
  } = props;
  const { canEdit } = usePlotNFTDetails(nft);
  const history = useHistory();

  async function handleAbsorbRewards() {
    if (!canEdit) {
      return;
    }

    history.push(`/dashboard/pool/${p2_singleton_puzzle_hash}/absorb-rewards`);
  }

  return children({
    absorb: handleAbsorbRewards,
    disabled: !canEdit,
  });
}
