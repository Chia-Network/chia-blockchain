import React, { useState, useEffect, useRef } from 'react';
import { useHistory } from 'react-router';
import { useDispatch, useSelector } from 'react-redux';
import { t, Trans } from '@lingui/macro';
import { AlertDialog } from '@chia/core';
import { ChevronRight as ChevronRightIcon } from '@material-ui/icons';
import { useForm, SubmitHandler } from 'react-hook-form';
import { ButtonLoading, Flex, Form, FormBackButton, Loading } from '@chia/core';
import { PlotHeaderSource } from '../PlotHeader';
import PlotAddChooseSize from './PlotAddChooseSize';
import PlotAddNumberOfPlots from './PlotAddNumberOfPlots';
import PlotAddSelectTemporaryDirectory from './PlotAddSelectTemporaryDirectory';
import PlotAddSelectFinalDirectory from './PlotAddSelectFinalDirectory';
import PlotAddNFT from './PlotAddNFT';
import { plotQueueAdd } from '../../../modules/plotQueue';
import { createPlotNFT } from '../../../modules/plotNFT';
import PlotAddConfig from '../../../types/PlotAdd';
import plotSizes, { defaultPlotSize } from '../../../constants/plotSizes';
import PlotNFTState from '../../../constants/PlotNFTState';
import useCurrencyCode from '../../../hooks/useCurrencyCode';
import type { RootState } from '../../../modules/rootReducer';
import toBech32m from '../../../util/toBech32m';
import useUnconfirmedPlotNFTs from '../../../hooks/useUnconfirmedPlotNFTs';
import useOpenDialog from '../../../hooks/useOpenDialog';

type FormData = PlotAddConfig & {
  p2_singleton_puzzle_hash?: string;
  createNFT?: boolean;
};

export default function PlotAdd() {
  const history = useHistory();
  const dispatch = useDispatch();
  const [loading, setLoading] = useState<boolean>(false);
  const currencyCode = useCurrencyCode();
  const fingerprint = useSelector(
    (state: RootState) => state.wallet_state.selected_fingerprint,
  );
  const addNFTref = useRef();
  const unconfirmedNFTs = useUnconfirmedPlotNFTs();
  const openDialog = useOpenDialog();
  const state = useSelector((state: RootState) => state.router.location.state);

  const methods = useForm<FormData>({
    shouldUnregister: false,
    defaultValues: {
      plotSize: defaultPlotSize.value,
      plotCount: 1,
      maxRam: defaultPlotSize.defaultRam,
      numThreads: 2,
      numBuckets: 128,
      queue: 'default',
      finalLocation: '',
      workspaceLocation: '',
      workspaceLocation2: '',
      farmerPublicKey: '',
      poolPublicKey: '',
      delay: 0,
      parallel: false,
      disableBitfieldPlotting: false,
      excludeFinalDir: false,
      p2_singleton_puzzle_hash: state?.p2_singleton_puzzle_hash ?? '',
      createNFT: false,
    },
  });

  const { watch, setValue } = methods;
  const plotSize = watch('plotSize');

  useEffect(() => {
    const plotSizeConfig = plotSizes.find((item) => item.value === plotSize);
    if (plotSizeConfig) {
      setValue('maxRam', plotSizeConfig.defaultRam);
    }
  }, [plotSize, setValue]);

  const handleSubmit: SubmitHandler<FormData> = async (data) => {
    try {
      setLoading(true);
      const { p2_singleton_puzzle_hash, delay, createNFT, ...rest } = data;
      const { farmerPublicKey, poolPublicKey } = rest;

      let selectedP2SingletonPuzzleHash = p2_singleton_puzzle_hash;

      if (!currencyCode) {
        throw new Error(t`Currency code is not defined`);
      }

      if (createNFT) {
        // create nft
        const nftData = await addNFTref.current?.getSubmitData();

        const {
          fee,
          initialTargetState,
          initialTargetState: { state },
        } = nftData;
        const { success, error, transaction, p2_singleton_puzzle_hash } =
          await dispatch(createPlotNFT(initialTargetState, fee));
        if (!success) {
          throw new Error(error ?? t`Unable to create plot NFT`);
        }

        if (!p2_singleton_puzzle_hash) {
          throw new Error(t`p2_singleton_puzzle_hash is not defined`);
        }

        unconfirmedNFTs.add({
          transactionId: transaction.name,
          state:
            state === 'SELF_POOLING'
              ? PlotNFTState.SELF_POOLING
              : PlotNFTState.FARMING_TO_POOL,
          poolUrl: initialTargetState.pool_url,
        });

        selectedP2SingletonPuzzleHash = p2_singleton_puzzle_hash;
      }

      const plotAddConfig = {
        ...rest,
        delay: delay * 60,
      };

      if (selectedP2SingletonPuzzleHash) {
        plotAddConfig.c = toBech32m(
          selectedP2SingletonPuzzleHash,
          currencyCode.toLowerCase(),
        );
      }

      if (
        !selectedP2SingletonPuzzleHash &&
        !farmerPublicKey &&
        !poolPublicKey &&
        fingerprint
      ) {
        plotAddConfig.fingerprint = fingerprint;
      }

      await dispatch(plotQueueAdd(plotAddConfig));

      history.push('/dashboard/plot');
    } catch (error) {
      await openDialog(<AlertDialog>{error.message}</AlertDialog>);
    } finally {
      setLoading(false);
    }
  };

  if (!currencyCode) {
    return (
      <Flex alignItems="center">
        <Loading />
      </Flex>
    );
  }

  return (
    <Form methods={methods} onSubmit={handleSubmit}>
      <PlotHeaderSource>
        <Flex alignItems="center">
          <ChevronRightIcon color="secondary" />
          <Trans>Add a Plot</Trans>
        </Flex>
      </PlotHeaderSource>
      <Flex flexDirection="column" gap={3}>
        <PlotAddChooseSize />
        <PlotAddNumberOfPlots />
        <PlotAddSelectTemporaryDirectory />
        <PlotAddSelectFinalDirectory />
        <PlotAddNFT ref={addNFTref} />
        <Flex gap={1}>
          <FormBackButton variant="outlined" />
          <ButtonLoading
            loading={loading}
            color="primary"
            type="submit"
            variant="contained"
          >
            <Trans>Create</Trans>
          </ButtonLoading>
        </Flex>
      </Flex>
    </Form>
  );
}
