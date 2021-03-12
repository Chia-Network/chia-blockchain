import React, { useEffect, useState } from 'react';
import { Trans } from '@lingui/macro';
import { useForm } from 'react-hook-form';
import { Alert } from '@material-ui/lab';
import styled from 'styled-components';
import { Flex, Form, TextField, Loading } from '@chia/core';
import { Button, Dialog, DialogActions, DialogTitle, DialogContent } from '@material-ui/core';
import { useDispatch } from 'react-redux';
import { getRewardTargets, setRewardTargets } from '../../modules/farmerMessages';

const StyledTextField = styled(TextField)`
  min-width: 640px;
`;

type FormData = {
  farmer_target: string;
  pool_target: string;
};

type Props = {
  open: boolean;
  onClose: () => void;
};

export default function FarmManageFarmingRewards(props: Props) {
  const { onClose, open } = props;
  const dispatch = useDispatch();
  const [showWarning, setShowWarning] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);
  const methods = useForm<FormData>({
    shouldUnregister: false,
    defaultValues: {
      farmer_target: '',
      pool_target: '',
    },
  });

  function handleClose() {
    onClose();
  }

  async function getCurrentValues() {
    const { setValue } = methods;
    setLoading(true);
    setShowWarning(false);
    setError(null);

    try {
      const response = await dispatch(getRewardTargets(true));
      // @ts-ignore
      setValue('farmer_target', response.farmer_target || '');
      // @ts-ignore
      setValue('pool_target', response.pool_target || '');

      // @ts-ignore
      if (!response.have_farmer_sk || !response.have_pool_sk) {
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
    const { farmer_target, pool_target } = values;
    setError(null);

    try {
      await dispatch(setRewardTargets(farmer_target, pool_target));
      handleClose();
    } catch (error) {
      setError(error);
    }
  }

  return (
    <Dialog
      disableBackdropClick
      disableEscapeKeyDown
      maxWidth="lg"
      aria-labelledby="manage-farming-rewards-title"
      open={open}
    >
      <Form
        methods={methods}
        onSubmit={handleSubmit}
      >
        <DialogTitle id="manage-farming-rewards-title">
          <Trans>Manage Your Farming Rewards Target Addresses</Trans>
        </DialogTitle>
        <DialogContent dividers>
          <Flex gap={2} flexDirection="column">
            {loading ? (
              <Flex justifyContent="center">
                <Loading />
              </Flex>
            ) : (
              <>
                {error && (
                  <Alert severity="error">{error.message}</Alert>
                )}
                {showWarning && (
                  <Alert severity="warning">
                    <Trans>
                      No private keys for one or both addresses. Safe only if you are sending rewards to another wallet.
                    </Trans>
                  </Alert>
                )}
                <StyledTextField
                  label={<Trans>Farmer Reward Address</Trans>}
                  name="farmer_target"
                  variant="filled"
                />
                <StyledTextField
                  label={<Trans>Pool Reward Address</Trans>}
                  name="pool_target"
                  variant="filled"
                />
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
