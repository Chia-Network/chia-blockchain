import React from 'react';
import { Trans } from '@lingui/macro';
import { useFormContext } from 'react-hook-form';
import { ButtonSelected, CardStep, Flex, TextField } from '@chia/core';
import { Typography } from '@material-ui/core';
import useSelectDirectory from '../../../hooks/useSelectDirectory';

export default function PlotAddSelectFinalDirectory() {
  const selectDirectory = useSelectDirectory();
  const { setValue, watch } = useFormContext();

  const finalLocation = watch('finalLocation');
  const hasFinalLocation = !!finalLocation;

  async function handleSelect() {
    const location = await selectDirectory();
    if (location) {
      setValue('finalLocation', location, { shouldValidate: true });
    }
  }

  return (
    <CardStep
      step="4"
      title={(
        <Trans id="PlotAddSelectFinalDirectory.title">Select Final Directory</Trans>
      )}
    >
      <Typography variant="subtitle1">
        <Trans id="PlotAddSelectFinalDirectory.description">
          Select the final destination for the folder where you would like the plot to be stored. We rcommend you use a large slow hard drive (like external HDD).
        </Trans>
      </Typography>

      <Flex gap={2}>
        <TextField
          onClick={handleSelect}
          fullWidth
          label={
            <Trans id="PlotAddSelectFinalDirectory.finalFolderLocation">
              Final folder location
            </Trans>
          }
          name='finalLocation'
          inputProps={{
            readOnly: true,
          }}
          variant="outlined"
          rules={{
            minLength: {
              value: 1,
              message: <Trans id="PlotAddSelectFinalDirectory.specifyFinalDirectory">Please specify final directory</Trans>,
            },
            required: {
              value: true,
              message: <Trans id="PlotAddSelectFinalDirectory.specifyFinalDirectory">Please specify final directory</Trans>,
            },
          }}
          required
        />
        <ButtonSelected onClick={handleSelect} size="large" variant="contained" selected={hasFinalLocation}>
          {hasFinalLocation ? (
            <Trans id="PlotterFinalLocation.selected">Selected</Trans>
          ) : (
            <Trans id="PlotterFinalLocation.browse">Browse</Trans>
          )}
        </ButtonSelected>
      </Flex>
    </CardStep>
  );
}
