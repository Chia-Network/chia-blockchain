import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import { AlertDialog, Fee, Back, ButtonLoading, Card, Flex, Form, TextField } from '@chia/core';
import { Box, Grid } from '@material-ui/core';
import { useDispatch } from 'react-redux';
import { useForm } from 'react-hook-form';
import { useHistory } from 'react-router';
import { createCATWalletFromToken } from '../../../modules/message';
import { chia_to_mojo } from '../../../util/chia';
import { openDialog } from '../../../modules/dialog';
import config from '../../../config/config';
import useShowError from '../../../hooks/useShowError';


type CreateExistingCATWalletData = {
  name: string;
  tail: string;
  symbol?: string;
};

export default function WalletCATCreateExisting() {
  const methods = useForm<CreateExistingCATWalletData>({
    shouldUnregister: false,
    defaultValues: {
      tail: '',
      name: '',
      symbol: '',
    },
  });
  const [loading, setLoading] = useState<boolean>(false);
  const dispatch = useDispatch();
  const history = useHistory();
  const showError = useShowError();

  async function handleSubmit(values: CreateExistingCATWalletData) {
    try {
      const { name, tail } = values;
      setLoading(true);


      if (!tail) {
        dispatch(
          openDialog(
            <AlertDialog>
              <Trans>Please enter a valid TAIL</Trans>
            </AlertDialog>,
          ),
        );
        return;
      }

      if (!name) {
        dispatch(
          openDialog(
            <AlertDialog>
              <Trans>Please enter a valid token name</Trans>
            </AlertDialog>,
          ),
        );
        return;
      }

      const walletId = await dispatch(createCATWalletFromToken({
        name,
        tail,
      }));
      history.push(`/dashboard/wallets/${walletId}`);
    } catch (error) {
      showError(error);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Form methods={methods} onSubmit={handleSubmit}>
      <Flex flexDirection="column" gap={3}>
        <Back variant="h5">
          <Trans>Create Token</Trans>
        </Back>
        <Card>
        <Grid spacing={2} direction="column" container>
            <Grid xs={12} md={8} lg={6} item>
          <Grid spacing={2} container>
            <Grid xs={12} item>
              <TextField
                  name="name"
                  variant="outlined"
                  label={<Trans>Name</Trans>}
                  fullWidth
                  autoFocus
                />
            </Grid>
            <Grid xs={12} item>
              <TextField
                name="tail"
                variant="outlined"
                label={<Trans>Token and Asset Issuance Limitations</Trans>}
                multiline
                fullWidth
              />
            </Grid>
          </Grid>
          </Grid>
          </Grid>
        </Card>
        <Box>
          <ButtonLoading
            type="submit"
            variant="contained"
            color="primary"
            loading={loading}
          >
            <Trans>Create</Trans>
          </ButtonLoading>
        </Box>
      </Flex>
    </Form>
  );
}
