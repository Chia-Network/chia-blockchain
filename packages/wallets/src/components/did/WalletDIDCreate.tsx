import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import {
  Amount,
  Form,
  AlertDialog,
  Back,
  Card,
  Flex,
  ButtonLoading,
  chiaToMojo,
} from '@chia/core';
import { Typography, Button, Box, TextField, Tooltip } from '@mui/material';
import { createState } from '../../../modules/createWallet';
import { useDispatch } from 'react-redux';
import { create_did_action } from '../../../modules/message';
import { openDialog } from '../../../modules/dialog';
import { useForm, Controller, useFieldArray } from 'react-hook-form';
import { Help as HelpIcon } from '@mui/icons-material';
import { divide } from 'lodash';
import { useNavigate } from 'react-router';

export default function WalletDIDCreate() {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const methods = useForm();
  const [loading, setLoading] = useState<boolean>(false);
  const { control } = methods;
  const { fields, append, remove } = useFieldArray({
    control,
    name: 'backup_dids',
  });

  async function onSubmit(data) {
    try {
      setLoading(true);
      const didArray = data.backup_dids?.map((item) => item.backupid) ?? [];
      let uniqDidArray = Array.from(new Set(didArray));
      uniqDidArray = uniqDidArray.filter((item) => item !== '');
      const amount_val = chiaToMojo(data.amount);
      if (
        amount_val === '' ||
        Number(amount_val) === 0 ||
        !Number(amount_val) ||
        isNaN(Number(amount_val))
      ) {
        dispatch(
          openDialog(
            <AlertDialog>
              <Trans>Please enter a valid numeric amount.</Trans>
            </AlertDialog>
          )
        );
        return;
      }
      if (amount_val % 2 !== 0) {
        dispatch(
          openDialog(
            <AlertDialog>
              <Trans>Amount must be an even amount.</Trans>
            </AlertDialog>
          )
        );
        return;
      }
      const num_of_backup_ids_needed = data.num_needed;
      if (
        num_of_backup_ids_needed === '' ||
        isNaN(Number(num_of_backup_ids_needed))
      ) {
        dispatch(
          openDialog(
            <AlertDialog>
              <Trans>
                Please enter a valid integer of 0 or greater for the number of
                Backup IDs needed for recovery.
              </Trans>
            </AlertDialog>
          )
        );
        return;
      }
      if (num_of_backup_ids_needed > uniqDidArray.length) {
        dispatch(
          openDialog(
            <AlertDialog>
              <Trans>
                The number of Backup IDs needed for recovery cannot exceed the
                number of Backup IDs added.
              </Trans>
            </AlertDialog>
          )
        );
        return;
      }
      const amount_plus = amount_val + 1;
      await dispatch(createState(true, true));
      const response = await dispatch(
        create_did_action(amount_plus, uniqDidArray, num_of_backup_ids_needed)
      );
      if (response && response.data && response.data.success === true) {
        navigate(`/dashboard/wallets/${response.data.wallet_id}`);
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <Form methods={methods} onSubmit={onSubmit}>
      <Flex flexDirection="column" gap={3}>
        <Back variant="h5">
          <Trans>Create Distributed Identity Wallet</Trans>
        </Back>
        <Card>
          <Flex flexDirection="column" gap={3}>
            <Flex flexDirection="column" gap={1}>
              <Flex alignItems="center" gap={1}>
                <Typography variant="subtitle1">Enter amount</Typography>
                <Tooltip title="The amount of Chia you enter must correspond to an even amount of mojos. One additional mojo will be added to the total amount for security purposes.">
                  <HelpIcon style={{ color: '#c8c8c8', fontSize: 12 }} />
                </Tooltip>
              </Flex>
              <Flex alignItems="center" gap={1}>
                <Flex flexGrow={1}>
                  <Amount
                    name="amount"
                    variant="outlined"
                    defaultValue=""
                    fullWidth
                  >
                    {() => (
                      <Flex display="flex" gap={1} alignItems="center">
                        <div>+ 1 mojo</div>
                        <Tooltip title="This additional mojo will be added to the total amount for security purposes.">
                          <HelpIcon
                            style={{ color: '#c8c8c8', fontSize: 12 }}
                          />
                        </Tooltip>
                      </Flex>
                    )}
                  </Amount>
                </Flex>
              </Flex>
            </Flex>
            <Flex flexDirection="column" gap={1}>
              <Flex alignItems="center" gap={1}>
                <Typography variant="subtitle1">
                  Enter number of Backup IDs needed for recovery
                </Typography>
                <Tooltip title="This number must be an integer greater than or equal to 0. It cannot exceed the number of Backup IDs added. You will be able to change this number as well as your list of Backup IDs.">
                  <HelpIcon style={{ color: '#c8c8c8', fontSize: 12 }} />
                </Tooltip>
              </Flex>
              <Flex flexDirection="row" justifyContent="space-between">
                <Box flexGrow={6}>
                  <Controller
                    as={TextField}
                    name="num_needed"
                    control={control}
                    label="Number of Backup IDs needed for recovery"
                    variant="outlined"
                    fullWidth
                    defaultValue=""
                  />
                </Box>
              </Flex>
            </Flex>
            <Flex flexDirection="column" gap={1}>
              <Box display="flex">
                <Box flexGrow={6}>
                  <Typography variant="subtitle1">
                    Add Backup IDs (optional):
                  </Typography>
                </Box>
              </Box>
              {fields.map((item, index) => (
                <Flex alignItems="stretch" key={item.id}>
                  <Box flexGrow={1}>
                    <Controller
                      as={TextField}
                      name={`backup_dids[${index}].backupid`}
                      control={control}
                      defaultValue=""
                      label="Backup ID"
                      variant="outlined"
                      fullWidth
                      color="secondary"
                    />
                  </Box>
                  <Button
                    onClick={() => remove(index)}
                    variant="contained"
                    color="danger"
                  >
                    <Trans>Delete</Trans>
                  </Button>
                </Flex>
              ))}
              <Box>
                <Button
                  onClick={() => {
                    append({ backupid: 'Backup ID' });
                  }}
                  variant="outlined"
                >
                  <Trans>Add Backup ID</Trans>
                </Button>
              </Box>
            </Flex>
          </Flex>
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
