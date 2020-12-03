import React from 'react';
import { useHistory } from 'react-router';
import { useDispatch, useSelector } from 'react-redux';
import { Trans } from '@lingui/macro';
import { Button } from '@material-ui/core';
import { ChevronRight as ChevronRightIcon } from '@material-ui/icons';
import { useForm, SubmitHandler } from 'react-hook-form';
import { Flex, Form } from '@chia/core';
import { PlotHeaderSource } from '../PlotHeader';
import PlotAddChooseSize from './PlotAddChooseSize';
import PlotAddNumberOfPlots from './PlotAddNumberOfPlots';
import PlotAddSelectTemporaryDirectory from './PlotAddSelectTemporaryDirectory';
import PlotAddSelectFinalDirectory from './PlotAddSelectFinalDirectory';
import { plotQueueAdd } from '../../../modules/plotQueue';
import PlotAddConfig from '../../../types/PlotAdd';
import type { RootState } from '../../../modules/rootReducer';

type FormData = PlotAddConfig;

export default function PlotAdd() {
  const history = useHistory();
  const dispatch = useDispatch();
  const fingerprint = useSelector((state: RootState) => state.wallet_state.selected_fingerprint);

  const methods = useForm<FormData>({
    shouldUnregister: false,
    defaultValues: {
      plotSize: 32,
      plotCount: 1,
      maxRam: 3072,
      numThreads: 2,
      numBuckets: 0,
      stripeSize: 65536,
      finalLocation: '',
      workspaceLocation: '',
      workspaceLocation2: '',
      delay: 0,
      parallel: false,
    },
  });

  const handleSubmit: SubmitHandler<FormData> = (data) => {
    dispatch(plotQueueAdd(fingerprint ? {
      ...data,
      fingerprint,
    } : data));

    history.push('/dashboard/plot');
  }

  return (
    <Form
      methods={methods}
      onSubmit={handleSubmit}>
      <PlotHeaderSource>
        <Flex alignItems="center">
          <ChevronRightIcon color="secondary" />
          <Trans id="PlotAdd.title">
            Add a Plot
          </Trans>
        </Flex>
      </PlotHeaderSource>
      <Flex flexDirection="column" gap={3}>
        <PlotAddChooseSize />
        <PlotAddNumberOfPlots />
        <PlotAddSelectTemporaryDirectory />
        <PlotAddSelectFinalDirectory />
        <div>
          <Button color="primary" type="submit" variant="contained">
            <Trans id="PlotAdd.createPlot">
              Create Plot
            </Trans>
          </Button>
        </div>
      </Flex>
    </Form>
  );
}
