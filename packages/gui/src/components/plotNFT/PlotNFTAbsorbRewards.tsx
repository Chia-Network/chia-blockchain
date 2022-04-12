import React, { useMemo, useState, ReactNode } from 'react';
import { Trans, t } from '@lingui/macro';
import { useNavigate } from 'react-router';
import {
  UnitFormat,
  CardStep,
  ButtonLoading,
  Loading,
  Fee,
  Flex,
  Form,
  State,
  mojoToChiaLocaleString,
  chiaToMojo,
  Back,
} from '@chia/core';
import { useForm } from 'react-hook-form';
import { usePwAbsorbRewardsMutation, useGetPlotNFTsQuery, useGetCurrentAddressQuery } from '@chia/api-react'
import { ChevronRight as ChevronRightIcon } from '@mui/icons-material';
import { Grid, Typography } from '@mui/material';
import { useParams } from 'react-router';
import { SubmitData } from './select/PlotNFTSelectPool';
import PlotNFTName from './PlotNFTName';
import useStandardWallet from '../../hooks/useStandardWallet';

type FormData = {
  fee?: string | number;
};

type Props = {
  headerTag?: ReactNode;
};

export default function PlotNFTAbsorbRewards(props: Props) {
  const { headerTag: HeaderTag } = props;

  const { plotNFTId } = useParams<{
    plotNFTId: string;
  }>();

  const { data, isLoading } = useGetPlotNFTsQuery();

  const [working, setWorking] = useState<boolean>(false);
  const { loading: loadingWallet } = useStandardWallet();
  const [pwAbsorbRewards] = usePwAbsorbRewardsMutation();
  const { data: address, isLoading: isLoadingAddress } = useGetCurrentAddressQuery({
    walletId: 1,
  });
  const navigate = useNavigate();
  const nft = useMemo(() => {
    return data?.nfts?.find(
      (nft) => nft.poolState.p2SingletonPuzzleHash === plotNFTId,
    );
  }, [data?.nfts, plotNFTId]);

  const methods = useForm<FormData>({
    defaultValues: {
      fee: '',
    },
  });

  async function handleSubmit(data: SubmitData) {
    try {
      setWorking(true);
      const walletId = nft?.poolWalletStatus.walletId;

      const { fee } = data;
      const feeMojos = chiaToMojo(fee);


      if (walletId === undefined) {
        throw new Error(t`Wallet is not defined`);
      }

      await pwAbsorbRewards({
        walletId,
        fee: feeMojos,
      }).unwrap();

      navigate(-1);
      /*
      if (history.length) {
        navigate(-1);
      } else {
        navigate('/dashboard/pool');
      }
      */
    } finally {
      setWorking(false);
    }
  }

  if (isLoading || isLoadingAddress) {
    return (
      <Loading>
        <Trans>Preparing Plot NFT</Trans>
      </Loading>
    );
  }

  if (loadingWallet) {
    return (
      <Loading>
        <Trans>Preparing standard wallet</Trans>
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
    walletBalance: { confirmedWalletBalance: balance },
  } = nft;

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

      <Form methods={methods} onSubmit={handleSubmit}>
        <Flex flexDirection="column" gap={3}>
          <Back form>
            <Typography variant="h5">
              <Trans>Claim Rewards</Trans>
            </Typography>
          </Back>
          <CardStep
            step="1"
            title={
              <Flex gap={1} alignItems="center">
                <Flex flexGrow={1}>
                  <Trans>Please Confirm</Trans>
                </Flex>
              </Flex>
            }
          >
            <Typography variant="subtitle1">
              <Trans>
                You will recieve{' '}
                <UnitFormat
                  value={mojoToChiaLocaleString(balance)}
                  display="inline"
                  state={State.SUCCESS}
                />{' '}
                to {address}
              </Trans>
            </Typography>

            <Grid container spacing={4}>
              <Grid xs={12} md={6} item>
                <Fee
                  name="fee"
                  type="text"
                  variant="filled"
                  label={<Trans>Fee</Trans>}
                  fullWidth
                />
              </Grid>
            </Grid>
          </CardStep>
          <Flex gap={1} justifyContent="flex-end">
            <ButtonLoading
              loading={working}
              color="primary"
              type="submit"
              variant="contained"
            >
              <Trans>Confirm</Trans>
            </ButtonLoading>
          </Flex>
        </Flex>
      </Form>
    </>
  );
}

PlotNFTAbsorbRewards.defaultProps = {
  headerTag: undefined,
};
