import React, { useMemo, ReactNode } from 'react';
import { Trans } from '@lingui/macro';
import { useHistory } from 'react-router';
import { useDispatch } from 'react-redux';
import { Flex, Loading } from '@hddcoin/core';
import { ChevronRight as ChevronRightIcon } from '@material-ui/icons';
import { useParams } from 'react-router';
import usePlotNFTs from '../../hooks/usePlotNFTs';
import { pwSelfPool, pwJoinPool } from '../../modules/plotNFT';
import PlotNFTSelectPool, { SubmitData } from './select/PlotNFTSelectPool';
import PlotNFTName from './PlotNFTName';

type Props = {
  headerTag?: ReactNode;
};

export default function PlotNFTChangePool(props: Props) {
  const { headerTag: HeaderTag } = props;

  const { plotNFTId } = useParams<{
    plotNFTId: string;
  }>();
  const { nfts, loading } = usePlotNFTs();
  const dispatch = useDispatch();
  const history = useHistory();
  const nft = useMemo(() => {
    return nfts?.find(
      (nft) => nft.pool_state.p2_singleton_puzzle_hash === plotNFTId,
    );
  }, [nfts, plotNFTId]);

  async function handleSubmit(data: SubmitData) {
    const walletId = nft?.pool_wallet_status.wallet_id;

    const {
      initialTargetState: {
        state,
        pool_url,
        relative_lock_height,
        target_puzzle_hash,
      },
    } = data;

    if (
      walletId === undefined ||
      pool_url === nft?.pool_state.pool_config.pool_url
    ) {
      return;
    }

    if (state === 'SELF_POOLING') {
      await dispatch(pwSelfPool(walletId));
    } else {
      await dispatch(
        pwJoinPool(
          walletId,
          pool_url,
          relative_lock_height,
          target_puzzle_hash,
        ),
      );
    }

    if (history.length) {
      history.goBack();
    } else {
      history.push('/dashboard/pool');
    }
  }

  if (loading) {
    return (
      <Loading>
        <Trans>Preparing Plot NFT</Trans>
      </Loading>
    );
  }

  if (!nft) {
    return (
      <Trans>
        Plot NFT with p2_singleton_puzzle_hash {plotNFTId} does not exists
      </Trans>
    );
  }

  const {
    pool_state: {
      pool_config: { pool_url },
    },
  } = nft;

  const defaultValues = {
    self: !pool_url,
    poolUrl: pool_url,
  };

  return (
    <>
      {HeaderTag && (
        <HeaderTag>
          <Flex alignItems="center">
            <ChevronRightIcon color="secondary" />
            <PlotNFTName nft={nft} variant="h6" />
          </Flex>
        </HeaderTag>
      )}
      <PlotNFTSelectPool
        onSubmit={handleSubmit}
        title={<Trans>Change Pool</Trans>}
        submitTitle={<Trans>Change</Trans>}
        defaultValues={defaultValues}
        hideFee
      />
    </>
  );
}

PlotNFTChangePool.defaultProps = {
  headerTag: undefined,
};
