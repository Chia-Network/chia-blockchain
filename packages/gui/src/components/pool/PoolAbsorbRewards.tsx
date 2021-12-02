import { useNavigate } from 'react-router';
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
      poolState: { p2SingletonPuzzleHash },
    },
  } = props;
  const { canEdit } = usePlotNFTDetails(nft);
  const navigate = useNavigate();

  async function handleAbsorbRewards() {
    if (!canEdit) {
      return;
    }

    navigate(`/dashboard/pool/${p2SingletonPuzzleHash}/absorb-rewards`);
  }

  return children({
    absorb: handleAbsorbRewards,
    disabled: !canEdit,
  });
}
