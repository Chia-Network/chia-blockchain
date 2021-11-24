import React from 'react';
import { Trans } from '@lingui/macro';
import { useFormContext } from 'react-hook-form';
import { useLocalStorage, writeStorage } from '@rehooks/local-storage';
import {
  AdvancedOptions,
  ButtonSelected,
  CardStep,
  Flex,
  TextField,
} from '@chia/core';
import { Typography } from '@material-ui/core';
import useSelectDirectory from '../../../hooks/useSelectDirectory';
import Plotter from '../../../types/Plotter';
import PlotLocalStorageKeys from '../../../constants/plotLocalStorage';

type Props = {
  step: number;
  plotter: Plotter;
};

export default function PlotAddSelectTemporaryDirectory(props: Props) {
  const { step } = props;
  const selectDirectory = useSelectDirectory();
  const { setValue, watch } = useFormContext();

  const workspaceLocation = watch('workspaceLocation');
  const hasWorkspaceLocation = !!workspaceLocation;
  const [defaultTmpDirPath] = useLocalStorage<string>(PlotLocalStorageKeys.TMPDIR);
  const [defaultTmp2DirPath] = useLocalStorage<string>(PlotLocalStorageKeys.TMP2DIR);

  const workspaceLocation2 = watch('workspaceLocation2');
  const hasWorkspaceLocation2 = !!workspaceLocation2;

  async function handleSelect() {
    const location = await selectDirectory({ defaultPath: defaultTmpDirPath || undefined });
    if (location) {
      setValue('workspaceLocation', location, { shouldValidate: true });
      writeStorage(PlotLocalStorageKeys.TMPDIR, location);
    }
  }

  async function handleSelect2() {
    const location = await selectDirectory({ defaultPath: defaultTmp2DirPath || undefined });
    if (location) {
      setValue('workspaceLocation2', location, { shouldValidate: true });
      writeStorage(PlotLocalStorageKeys.TMP2DIR, location);
    }
  }

  return (
    <CardStep step={step} title={<Trans>Select Temporary Directory</Trans>}>
      <Typography variant="subtitle1">
        <Trans>
          Select the temporary destination for the folder where you would like
          the plot to be stored. We recommend you use a fast drive.
        </Trans>
      </Typography>

      <Flex gap={2}>
        <TextField
          onClick={handleSelect}
          fullWidth
          label={<Trans>Temporary folder location</Trans>}
          name="workspaceLocation"
          inputProps={{
            readOnly: true,
          }}
          variant="filled"
          rules={{
            minLength: {
              value: 1,
              message: <Trans>Please specify temporary directory</Trans>,
            },
            required: {
              value: true,
              message: <Trans>Please specify temporary directory</Trans>,
            },
          }}
          required
        />
        <ButtonSelected
          onClick={handleSelect}
          size="large"
          variant="outlined"
          selected={hasWorkspaceLocation}
          nowrap
        >
          {hasWorkspaceLocation ? (
            <Trans>Selected</Trans>
          ) : (
            <Trans>Browse</Trans>
          )}
        </ButtonSelected>
      </Flex>

      <AdvancedOptions>
        <Flex flexDirection="column" gap={2}>
          <Typography variant="h6">
            <Trans>Select 2nd Temporary Directory</Trans>
          </Typography>
          <Flex gap={2}>
            <TextField
              onClick={handleSelect2}
              fullWidth
              label={<Trans>Second temporary folder location</Trans>}
              name="workspaceLocation2"
              inputProps={{
                readOnly: true,
              }}
              variant="filled"
            />
            <ButtonSelected
              onClick={handleSelect2}
              size="large"
              variant="outlined"
              selected={hasWorkspaceLocation2}
              nowrap
            >
              {hasWorkspaceLocation2 ? (
                <Trans>Selected</Trans>
              ) : (
                <Trans>Browse</Trans>
              )}
            </ButtonSelected>
          </Flex>
          <Typography color="textSecondary">
            <Trans>
              If none selected, then it will default to the temporary directory.
            </Trans>
          </Typography>
        </Flex>
      </AdvancedOptions>
    </CardStep>
  );
}
