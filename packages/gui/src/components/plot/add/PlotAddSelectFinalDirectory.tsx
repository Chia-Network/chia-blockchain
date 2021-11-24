import React from 'react';
import { Trans } from '@lingui/macro';
import { useFormContext } from 'react-hook-form';
import { useLocalStorage, writeStorage } from '@rehooks/local-storage';
import { ButtonSelected, CardStep, Flex, TextField } from '@chia/core';
import { Typography } from '@material-ui/core';
import useSelectDirectory from '../../../hooks/useSelectDirectory';
import Plotter from '../../../types/Plotter';
import PlotLocalStorageKeys from '../../../constants/plotLocalStorage';

type Props = {
  step: number;
  plotter: Plotter
};

export default function PlotAddSelectFinalDirectory(props: Props) {
  const { step } = props;
  const selectDirectory = useSelectDirectory();
  const { setValue, watch } = useFormContext();

  const finalLocation = watch('finalLocation');
  const hasFinalLocation = !!finalLocation;
  const [defaultFinalDirPath] = useLocalStorage<string>(PlotLocalStorageKeys.FINALDIR);

  async function handleSelect() {
    const location = await selectDirectory({ defaultPath: defaultFinalDirPath || undefined });
    if (location) {
      setValue('finalLocation', location, { shouldValidate: true });
      writeStorage(PlotLocalStorageKeys.FINALDIR, location);
    }
  }

  return (
    <CardStep step={step} title={<Trans>Select Final Directory</Trans>}>
      <Typography variant="subtitle1">
        <Trans>
          Select the final destination for the folder where you would like the
          plot to be stored. We recommend you use a large slow hard drive (like
          external HDD).
        </Trans>
      </Typography>

      <Flex gap={2}>
        <TextField
          onClick={handleSelect}
          fullWidth
          label={<Trans>Final folder location</Trans>}
          name="finalLocation"
          inputProps={{
            readOnly: true,
          }}
          variant="filled"
          rules={{
            minLength: {
              value: 1,
              message: <Trans>Please specify final directory</Trans>,
            },
            required: {
              value: true,
              message: <Trans>Please specify final directory</Trans>,
            },
          }}
          required
        />
        <ButtonSelected
          onClick={handleSelect}
          size="large"
          variant="outlined"
          selected={hasFinalLocation}
          nowrap
        >
          {hasFinalLocation ? <Trans>Selected</Trans> : <Trans>Browse</Trans>}
        </ButtonSelected>
      </Flex>
    </CardStep>
  );
}
