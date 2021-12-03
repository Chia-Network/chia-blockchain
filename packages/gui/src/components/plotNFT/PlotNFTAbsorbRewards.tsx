import React, { useMemo, useState, ReactNode } from 'react';
import { Trans } from '@lingui/macro';
import { useNavigate } from 'react-router';
import {
  UnitFormat,
  CardStep,
  ButtonLoading,
  Loading,
  Fee,
  Flex,
  Form,
  FormBackButton,
  State,
  mojoToChiaLocaleString,
  chiaToMojo,
} from '@chia/core';
import { useForm } from 'react-hook-form';
import { usePwAbsorbRewardsMutation, useGetPlotNFTsQuery } from '@chia/api-react'
import { ChevronRight as ChevronRightIcon } from '@material-ui/icons';
import { Grid, Typography } from '@material-ui/core';
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
  const { wallet, loading: loadingWallet } = useStandardWallet();
  const [ pwAbsorbRewards] = usePwAbsorbRewardsMutation();
  const navigate = useNavigate();
  const nft = useMemo(() => {
    return data?.nfts?.find(
      (nft) => nft.poolState.p2SingletonPuzzleHash === plotNFTId,
    );
  }, [data?.nfts, plotNFTId]);

  const methods = useForm<FormData>({
    shouldUnregister: false,
    defaultValues: {
      fee: '',
    },
  });

  async function handleSubmit(data: SubmitData) {
    try {
      setWorking(true);
      const walletId = nft?.poolWalletStatus.walletId;
      const address = wallet?.address;

      const { fee } = data;

      const feeMojos = chiaToMojo(fee);

      if (walletId === undefined || !address) {
        return;
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

  if (isLoading) {
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
                to {wallet?.address}
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
          <Flex gap={1}>
            <FormBackButton variant="outlined" />
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
