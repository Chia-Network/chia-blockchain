import React, { ReactNode } from 'react';
import { useNavigate } from 'react-router';
import { Trans } from '@lingui/macro';
import { useCreateNewPoolWalletMutation } from '@chia/api-react';
import { ChevronRight as ChevronRightIcon } from '@mui/icons-material';
import { Flex, Suspender } from '@chia/core';
import PlotNFTState from '../../constants/PlotNFTState';
import useUnconfirmedPlotNFTs from '../../hooks/useUnconfirmedPlotNFTs';
import PlotNFTSelectPool, { SubmitData } from './select/PlotNFTSelectPool';

type Props = {
  headerTag?: ReactNode;
};

export default function PlotNFTAdd(props: Props) {
  const { headerTag: HeaderTag } = props;
  const navigate = useNavigate();
  const { isLoading: isLoadingUnconfirmedPlotNFTs, add: addUnconfirmedPlotNFT } = useUnconfirmedPlotNFTs();
  const [createNewPoolWallet] = useCreateNewPoolWalletMutation();

  if (isLoadingUnconfirmedPlotNFTs) {
    return <Suspender />
  }

  async function handleSubmit(data: SubmitData) {
    const {
      fee,
      initialTargetState,
      initialTargetState: { state },
    } = data;

    const { transaction, ...rest } = await createNewPoolWallet({
      initialTargetState, 
      fee,
    }).unwrap();

    addUnconfirmedPlotNFT({
      transactionId: transaction.name,
      state:
        state === 'SELF_POOLING'
          ? PlotNFTState.SELF_POOLING
          : PlotNFTState.FARMING_TO_POOL,
      poolUrl: initialTargetState.poolUrl,
    });

    navigate('/dashboard/pool');
  }

  return (
    <>
      {HeaderTag && (
        <HeaderTag>
          <Flex alignItems="center">
            <ChevronRightIcon color="secondary" />
            <Trans>Add a Plot NFT</Trans>
          </Flex>
        </HeaderTag>
      )}
      <PlotNFTSelectPool
        onSubmit={handleSubmit}
        title={<Trans>Want to Join a Pool? Create a Plot NFT</Trans>}
        description={
          <Trans>
            Join a pool and get consistent XCH farming rewards. The average
            returns are the same, but it is much less volatile. Assign plots to
            a plot NFT. You can easily switch pools without having to re-plot.
          </Trans>
        }
      />
    </>
  );
}

PlotNFTAdd.defaultProps = {
  step: undefined,
  onCancel: undefined,
};
