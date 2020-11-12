import React from 'react';
import { useHistory } from 'react-router';
import { useDispatch } from 'react-redux';
import { Trans } from '@lingui/macro';
import { Button } from '@material-ui/core';
import { ChevronRight as ChevronRightIcon } from '@material-ui/icons';
import { useForm, SubmitHandler } from 'react-hook-form';
import { Flex, Form } from '@chia/core';
import { PlotHeaderSource } from '../Plot';
import PlotAddChooseSize from './PlotAddChooseSize';
import PlotAddNumberOfPlots from './PlotAddNumberOfPlots';
import PlotAddSelectTemporaryDirectory from './PlotAddSelectTemporaryDirectory';
import PlotAddSelectFinalDirectory from './PlotAddSelectFinalDirectory';
import { startPlotting } from '../../../modules/plotter_messages';

type FormData = {
  plotSize: number;
  plotCount: number;
  maxRam: number;
  numThreads: number;
  numBuckets: number,
  stripeSize: number,
  finalLocation: string;
  workspaceLocation: string;
  workspaceLocation2: string;
};

export default function PlotAdd(): JSX.Element {
  const history = useHistory();
  const dispatch = useDispatch();

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
    },
  });

  const handleSubmit: SubmitHandler<FormData> = (data) => {
    const {
      plotSize,
      plotCount,
      workspaceLocation,
      workspaceLocation2,
      finalLocation,
      maxRam,
      numBuckets,
      numThreads,
      stripeSize,
    } = data;

    dispatch(startPlotting(
      plotSize,
      plotCount,
      workspaceLocation,
      workspaceLocation2 || workspaceLocation,
      finalLocation,
      maxRam,
      numBuckets,
      numThreads,
      stripeSize,
    ));

    history.push('/dashboard/plot');
  }

  return (
    <Form<FormData>
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
