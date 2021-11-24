import React, { useState, useEffect, useRef } from 'react';
import { useHistory } from 'react-router';
import { useDispatch, useSelector } from 'react-redux';
import { t, Trans } from '@lingui/macro';
import { AlertDialog } from '@chia/core';
import { ChevronRight as ChevronRightIcon } from '@material-ui/icons';
import { useForm, SubmitHandler } from 'react-hook-form';
import { ButtonLoading, Flex, Form, FormBackButton, Loading } from '@chia/core';
import { PlotHeaderSource } from '../PlotHeader';
import PlotAddChoosePlotter from './PlotAddChoosePlotter';
import PlotAddChooseSize from './PlotAddChooseSize';
import PlotAddNumberOfPlots from './PlotAddNumberOfPlots';
import PlotAddSelectTemporaryDirectory from './PlotAddSelectTemporaryDirectory';
import PlotAddSelectFinalDirectory from './PlotAddSelectFinalDirectory';
import PlotAddNFT from './PlotAddNFT';
import { plotQueueAdd } from '../../../modules/plotQueue';
import { createPlotNFT } from '../../../modules/plotNFT';
import PlotAddConfig from '../../../types/PlotAdd';
import plotSizes from '../../../constants/plotSizes';
import PlotNFTState from '../../../constants/PlotNFTState';
import PlotterName from '../../../constants/PlotterName';
import { defaultPlotter } from '../../../modules/plotterConfiguration';
import useCurrencyCode from '../../../hooks/useCurrencyCode';
import type { RootState } from '../../../modules/rootReducer';
import toBech32m from '../../../util/toBech32m';
import useUnconfirmedPlotNFTs from '../../../hooks/useUnconfirmedPlotNFTs';
import useOpenDialog from '../../../hooks/useOpenDialog';
import { getPlotters } from '../../../modules/plotter_messages';

type FormData = PlotAddConfig & {
  p2_singleton_puzzle_hash?: string;
  createNFT?: boolean;
};

export default function PlotAdd() {
  const history = useHistory();
  const dispatch = useDispatch();
  const [loading, setLoading] = useState<boolean>(false);
  const [fetchedPlotters, setFetchedPlotters] = useState<boolean>(false);
  const currencyCode = useCurrencyCode();
  const fingerprint = useSelector(
    (state: RootState) => state.wallet_state.selected_fingerprint,
  );
  const addNFTref = useRef();
  const unconfirmedNFTs = useUnconfirmedPlotNFTs();
  const openDialog = useOpenDialog();
  const state = useSelector((state: RootState) => state.router.location.state);
  const { availablePlotters } = useSelector((state: RootState) => state.plotter_configuration);

  const otherDefaults = {
    plotCount: 1,
    queue: 'default',
    finalLocation: '',
    workspaceLocation: '',
    workspaceLocation2: '',
    farmerPublicKey: '',
    poolPublicKey: '',
    excludeFinalDir: false,
    p2_singleton_puzzle_hash: state?.p2_singleton_puzzle_hash ?? '',
    createNFT: false,
  };

  const defaultsForPlotter = (plotterName: PlotterName) => {
    const plotterDefaults = availablePlotters[plotterName]?.defaults ?? defaultPlotter().defaults;
    const plotSize = plotterDefaults.plotSize;
    const maxRam = plotSizes.find((element) => element.value === plotSize)?.defaultRam;
    const defaults = {
      ...plotterDefaults,
      ...otherDefaults,
      maxRam: maxRam,
    };

    return defaults;
  }

  const methods = useForm<FormData>({
    shouldUnregister: false,
    defaultValues: defaultsForPlotter(PlotterName.CHIAPOS),
  });

  const { watch, setValue, reset } = methods;
  const plotterName = watch('plotterName') as PlotterName;
  const plotSize = watch('plotSize');

  useEffect(() => {
    if (!fetchedPlotters) {
      dispatch(getPlotters());
      setFetchedPlotters(true);
    }
  }, [fetchedPlotters]);

  let plotter = availablePlotters[plotterName] ?? defaultPlotter();
  let step: number = 1;
  const allowTempDirectorySelection: boolean = plotter.options.haveBladebitOutputDir === false;

  useEffect(() => {
    const plotSizeConfig = plotSizes.find((item) => item.value === plotSize);
    if (plotSizeConfig) {
      setValue('maxRam', plotSizeConfig.defaultRam);
    }
  }, [plotSize, setValue]);

  const handlePlotterChanged = (newPlotterName: PlotterName) => {
    const defaults = defaultsForPlotter(newPlotterName);
    reset(defaults);
  };

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
    return <Loading center />;
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
        <PlotAddChoosePlotter step={step++} onChange={handlePlotterChanged} />
        <PlotAddChooseSize step={step++} plotter={plotter} />
        <PlotAddNumberOfPlots step={step++} plotter={plotter} />
        {allowTempDirectorySelection && (
          <PlotAddSelectTemporaryDirectory step={step++} plotter={plotter} />
        )}
        <PlotAddSelectFinalDirectory step={step++} plotter={plotter} />
        <PlotAddNFT ref={addNFTref} step={step++} plotter={plotter} />
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
