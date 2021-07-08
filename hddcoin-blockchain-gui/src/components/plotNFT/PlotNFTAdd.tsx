import React, { ReactNode } from 'react';
import { useHistory } from 'react-router';
import { useDispatch } from 'react-redux';
import { Trans } from '@lingui/macro';
import { ChevronRight as ChevronRightIcon } from '@material-ui/icons';
import { Flex } from '@hddcoin/core';
import { createPlotNFT } from '../../modules/plotNFT';
import PlotNFTState from '../../constants/PlotNFTState';
import useUnconfirmedPlotNFTs from '../../hooks/useUnconfirmedPlotNFTs';
import PlotNFTSelectPool, { SubmitData } from './select/PlotNFTSelectPool';

type Props = {
  headerTag?: ReactNode;
};

export default function PlotNFTAdd(props: Props) {
  const { headerTag: HeaderTag } = props;
  const dispatch = useDispatch();
  const history = useHistory();
  const unconfirmedNFTs = useUnconfirmedPlotNFTs();

  async function handleSubmit(data: SubmitData) {
    const {
      fee,
      initialTargetState,
      initialTargetState: { state },
    } = data;
    const { success, transaction } = await dispatch(
      createPlotNFT(initialTargetState, fee),
    );
    if (success) {
      unconfirmedNFTs.add({
        transactionId: transaction.name,
        state:
          state === 'SELF_POOLING'
            ? PlotNFTState.SELF_POOLING
            : PlotNFTState.FARMING_TO_POOL,
        poolUrl: initialTargetState.pool_url,
      });

      history.push('/dashboard/pool');
    }
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
            Join a pool and get consistent HDD farming rewards. The average
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
