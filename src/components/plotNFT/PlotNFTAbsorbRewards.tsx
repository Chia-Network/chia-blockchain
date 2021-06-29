import React, { useMemo, useState, ReactNode } from 'react';
import { Trans } from '@lingui/macro';
import { useHistory } from 'react-router';
import { useDispatch } from 'react-redux';
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
} from '@chia/core';
import { useForm } from 'react-hook-form';
import { ChevronRight as ChevronRightIcon } from '@material-ui/icons';
import { Grid, Typography } from '@material-ui/core';
import { useParams } from 'react-router';
import usePlotNFTs from '../../hooks/usePlotNFTs';
import { pwAbsorbRewards } from '../../modules/plotNFT';
import PlotNFTSelectPool, { SubmitData } from './select/PlotNFTSelectPool';
import PlotNFTName from './PlotNFTName';
import { mojo_to_chia, chia_to_mojo } from '../../util/chia';
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
  const [working, setWorking] = useState<boolean>(false);
  const { nfts, loading } = usePlotNFTs();
  const { wallet, loading: loadingWallet } = useStandardWallet();
  const dispatch = useDispatch();
  const history = useHistory();
  const nft = useMemo(() => {
    return nfts?.find(
      (nft) => nft.pool_state.p2_singleton_puzzle_hash === plotNFTId,
    );
  }, [nfts, plotNFTId]);

  const methods = useForm<FormData>({
    shouldUnregister: false,
    defaultValues: {
      fee: '',
    },
  });

  async function handleSubmit(data: SubmitData) {
    try {
      setWorking(true);
      const walletId = nft?.pool_wallet_status.wallet_id;
      const address = wallet?.address;

      const { fee } = data;

      const feeMojos = chia_to_mojo(fee);

      if (walletId === undefined || !address) {
        return;
      }

      await dispatch(pwAbsorbRewards(walletId, feeMojos));

      if (history.length) {
        history.goBack();
      } else {
        history.push('/dashboard/pool');
      }
    } finally {
      setWorking(false);
    }
  }

  if (loading) {
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
    wallet_balance: { confirmed_wallet_balance: balance },
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
                <Flex flexGrow={1}>Please Confirm</Flex>
              </Flex>
            }
          >
            <Typography variant="subtitle1">
              <Trans>
                You will recieve{' '}
                <UnitFormat
                  value={mojo_to_chia(BigInt(balance))}
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
