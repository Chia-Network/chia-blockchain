import React, { useMemo, ReactNode } from 'react';
import { Trans } from '@lingui/macro';
import { useNavigate } from 'react-router';
import { useGetPlotNFTsQuery, usePwSelfPoolMutation, usePwJoinPoolMutation } from '@chia/api-react';
import { Flex, State, Loading, StateTypography } from '@chia/core';
import { ChevronRight as ChevronRightIcon } from '@mui/icons-material';
import { useParams } from 'react-router';
import PlotNFTSelectPool, { SubmitData } from './select/PlotNFTSelectPool';
import PlotNFTName from './PlotNFTName';
import PlotNFTStateEnum from '../../constants/PlotNFTState';

type Props = {
  headerTag?: ReactNode;
};

export default function PlotNFTChangePool(props: Props) {
  const { headerTag: HeaderTag } = props;
  const { data, isLoading } = useGetPlotNFTsQuery();
  const [pwSelfPool] = usePwSelfPoolMutation();
  const [pwJoinPool] = usePwJoinPoolMutation();

  const { plotNFTId } = useParams<{
    plotNFTId: string;
  }>();

  const navigate = useNavigate();
  const nft = useMemo(() => {
    return data?.nfts?.find(
      (nft) => nft.poolState.p2SingletonPuzzleHash === plotNFTId,
    );
  }, [data?.nfts, plotNFTId]);


  const state = nft?.poolWalletStatus?.current?.state;
  const isDoubleFee = state === PlotNFTStateEnum.FARMING_TO_POOL;

  async function handleSubmit(data: SubmitData) {
    const walletId = nft?.poolWalletStatus.walletId;

    const {
      initialTargetState: {
        state,
        poolUrl,
        relativeLockHeight,
        targetPuzzleHash,
      },
      fee,
    } = data;

    if (
      walletId === undefined ||
      poolUrl === nft?.poolState.poolConfig.poolUrl
    ) {
      return;
    }

    if (state === 'SELF_POOLING') {
      await pwSelfPool({
        walletId, 
        fee,
      }).unwrap();
    } else {
      await pwJoinPool({
        walletId,
        poolUrl,
        relativeLockHeight,
        targetPuzzleHash,
        fee,
      }).unwrap();
    }

    navigate(-1);
    /*
    if (history.length) {
      history.goBack();
    } else {
      navigate('/dashboard/pool');
    }
    */
  }

  if (isLoading) {
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
    poolState: {
      poolConfig: { poolUrl },
    },
  } = nft;

  const defaultValues = {
    self: !poolUrl,
    poolUrl: poolUrl,
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
        feeDescription={isDoubleFee && (
          <StateTypography variant="body2" state={State.WARNING}>
            <Trans>Fee is used TWICE: once to leave pool, once to join.</Trans>
          </StateTypography>
        )}
      />
    </>
  );
}
