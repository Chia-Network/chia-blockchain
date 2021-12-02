import React, { useEffect, useState } from 'react';
import { Trans } from '@lingui/macro';
import { useForm } from 'react-hook-form';
import { Alert } from '@material-ui/lab';
import styled from 'styled-components';
import { Flex, Form, TextField, Loading } from '@chia/core';
import { useSetRewardTargetsMutation, useGetRewardTargetsMutation } from '@chia/api-react';
import {
  Button,
  Dialog,
  DialogActions,
  DialogTitle,
  DialogContent,
  Typography,
} from '@material-ui/core';
import { bech32m } from 'bech32';

const StyledTextField = styled(TextField)`
  min-width: 640px;
`;

type FormData = {
  farmerTarget: string;
  poolTarget: string;
};

type Props = {
  open: boolean;
  onClose: () => void;
};

export default function FarmManageFarmingRewards(props: Props) {
  const { onClose, open } = props;
  const [setRewardTargets] = useSetRewardTargetsMutation();
  const [getRewardTargets] = useGetRewardTargetsMutation();
  
  const [showWarning, setShowWarning] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);
  const methods = useForm<FormData>({
    mode: 'onChange',
    shouldUnregister: false,
    defaultValues: {
      farmerTarget: '',
      poolTarget: '',
    },
  });

  const {
    register,
    formState: { errors },
  } = methods;

  function handleClose() {
    onClose();
  }
  function handleDialogClose(event: any, reason: any) {
      if (reason !== 'backdropClick' || reason !== 'EscapeKeyDown') {
      onClose();
      }}

      function checkAddress(stringToCheck: string): boolean {
    try {
      bech32m.decode(stringToCheck);
      return true;
    }
    catch {
      return false;
    }
  }

  async function getCurrentValues() {
    const { setValue } = methods;
    setLoading(true);
    setShowWarning(false);
    setError(null);

    try {
      const response = await getRewardTargets({
        searchForPrivateKey: true,
      }).unwrap();
      // @ts-ignore
      setValue('farmerTarget', response.farmerTarget || '');
      // @ts-ignore
      setValue('poolTarget', response.poolTarget || '');

      // @ts-ignore
      if (!response.haveFarmerSk || !response.havePoolSk) {
        setShowWarning(true);
      }
    } catch (error) {
      setError(error);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    getCurrentValues();
  }, []); // eslint-disable-line

  async function handleSubmit(values: FormData) {
    const { farmerTarget, poolTarget } = values;
    setError(null);

    try {
      await setRewardTargets({
        farmerTarget, 
        poolTarget,
      }).unwrap();
      handleClose();
    } catch (error) {
      setError(error);
    }
  }

  return (
    <Dialog
      onClose={handleDialogClose}
      maxWidth="lg"
      aria-labelledby="manage-farming-rewards-title"
      open={open}
    >
      <Form methods={methods} onSubmit={handleSubmit}>
        <DialogTitle id="manage-farming-rewards-title">
          <Trans>Manage Your Farming Rewards Target Addresses</Trans>
        </DialogTitle>
        <DialogContent dividers>
          <Flex gap={2} flexDirection="column">
            {loading ? (
              <Loading center />
            ) : (
              <>
                {error && <Alert severity="error">{error.message}</Alert>}
                {errors.farmerTarget &&
                  errors.farmerTarget.type === 'required' && (
                    <Alert severity="error">
                      <Trans>Farmer Reward Address must not be empty.</Trans>
                    </Alert>
                  )}
                {errors.farmerTarget &&
                  errors.farmerTarget.type === 'validate' && (
                    <Alert severity="error">
                      <Trans>
                        Farmer Reward Address is not properly formatted.
                      </Trans>
                    </Alert>
                  )}
                {errors.poolTarget && errors.poolTarget.type === 'required' && (
                  <Alert severity="error">
                    <Trans>Pool Reward Address must not be empty.</Trans>
                  </Alert>
                )}
                {errors.poolTarget && errors.poolTarget.type === 'validate' && (
                  <Alert severity="error">
                    <Trans>
                      Pool Reward Address is not properly formatted.
                    </Trans>
                  </Alert>
                )}
                {showWarning && (
                  <Alert severity="warning">
                    <Trans>
                      No private keys for one or both addresses. Safe only if
                      you are sending rewards to another wallet.
                    </Trans>
                  </Alert>
                )}
                <StyledTextField
                  label={<Trans>Farmer Reward Address</Trans>}
                  name="farmerTarget"
                  variant="filled"
                  inputProps={{ spellCheck: false }}
                  {...register('farmerTarget', {
                    required: true,
                    validate: checkAddress,
                  })}
                />
                <StyledTextField
                  label={<Trans>Pool Reward Address</Trans>}
                  name="poolTarget"
                  variant="filled"
                  inputProps={{ spellCheck: false }}
                  {...register('poolTarget', {
                    required: true,
                    validate: checkAddress,
                  })}
                />

                <Typography variant="body2" color="textSecondary">
                  <Trans>
                    Note that this does not change your pooling payout
                    addresses. This only affects old format plots, and the
                    0.25XCH reward for pooling plots.
                  </Trans>
                </Typography>
              </>
            )}
          </Flex>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose} color="secondary">
            <Trans>Cancel</Trans>
          </Button>
          <Button type="submit" autoFocus color="primary">
            <Trans>Save</Trans>
          </Button>
        </DialogActions>
      </Form>
    </Dialog>
  );
}

FarmManageFarmingRewards.defaultProps = {
  open: false,
  onClose: () => {},
};
