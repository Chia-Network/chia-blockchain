import React from 'react';
import {
  Typography,
  Button,
  Box,
  TextField,
  Backdrop,
  CircularProgress,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/core/styles';

import {
  createState,
  changeCreateWallet,
  CREATE_DID_WALLET_OPTIONS,
} from '../../../modules/createWallet';
import { useDispatch, useSelector } from 'react-redux';
import ArrowBackIosIcon from '@material-ui/icons/ArrowBackIos';
import { useStyles } from './WalletCreate';
import { create_did_action } from '../../../modules/message';
import { chia_to_mojo } from '../../../util/chia';
import { openDialog } from '../../../modules/dialog';
import { useForm, Controller, useFieldArray } from 'react-hook-form';

export const customStyles = makeStyles((theme) => ({
  input: {
    marginLeft: theme.spacing(3),
    height: 56,
  },
  inputLeft: {
    marginLeft: theme.spacing(3),
    width: '75%',
    height: 56,
  },
  inputDIDs: {
    paddingTop: theme.spacing(3),
    marginLeft: theme.spacing(0),
  },
  inputDID: {
    marginLeft: theme.spacing(0),
    marginBottom: theme.spacing(2),
    width: '50%',
    height: 56,
  },
  inputRight: {
    marginRight: theme.spacing(3),
    marginLeft: theme.spacing(6),
    height: 56,
  },
  sendButton: {
    marginLeft: theme.spacing(6),
    marginRight: theme.spacing(2),
    height: 56,
    width: 150,
  },
  addButton: {
    marginTop: theme.spacing(2),
    marginBottom: theme.spacing(2),
    height: 56,
    width: 50,
  },
  card: {
    paddingTop: theme.spacing(10),
    height: 200,
  },
  topCard: {
    height: 100,
  },
  subCard: {
    height: 100,
  },
  topTitleCard: {
    paddingTop: theme.spacing(6),
    paddingBottom: theme.spacing(1),
  },
  titleCard: {
    paddingBottom: theme.spacing(1),
  },
  inputTitleLeft: {
    paddingTop: theme.spacing(3),
    marginLeft: theme.spacing(3),
    width: '50%',
  },
  inputTitleRight: {
    marginLeft: theme.spacing(3),
    width: '50%',
  },
  ul: {
    listStyle: 'none',
  },
  sideButton: {
    marginTop: theme.spacing(0),
    marginBottom: theme.spacing(2),
    width: 50,
    height: 56,
  },
}));

export const CreateDIDWallet = () => {
  const classes = useStyles();
  const custom = customStyles();
  const dispatch = useDispatch();
  var pending = useSelector((state) => state.create_options.pending);
  var created = useSelector((state) => state.create_options.created);

  const { handleSubmit, control } = useForm();

  const { fields, append, remove } = useFieldArray({
    control,
    name: 'backup_dids',
  });

  const onSubmit = (data) => {
    const didArray = data.backup_dids?.map((item) => item.backupid) ?? [];
    if (
      data.amount === '' ||
      Number(data.amount) === 0 ||
      !Number(data.amount) ||
      isNaN(Number(data.amount))
    ) {
      dispatch(openDialog('Please enter a valid numeric amount'));
      return;
    }
    var amount_val = chia_to_mojo(parseInt(data.amount));
    const num_of_backup_ids_needed = parseInt(1);
    dispatch(createState(true, true));
    dispatch(create_did_action(amount_val, didArray, num_of_backup_ids_needed));
  };

  function goBack() {
    dispatch(changeCreateWallet(CREATE_DID_WALLET_OPTIONS));
  }

  return (
    <div>
      <div className={classes.cardTitle}>
        <Box display="flex">
          <Box>
            <Button onClick={goBack}>
              <ArrowBackIosIcon> </ArrowBackIosIcon>
            </Button>
          </Box>
          <Box flexGrow={1} className={classes.title}>
            <Typography component="h6" variant="h6">
              Create Distributed Identity Wallet
            </Typography>
          </Box>
        </Box>
      </div>
      <form onSubmit={handleSubmit(onSubmit)}>
        <div className={custom.topTitleCard}>
          <Box display="flex">
            <Box flexGrow={6} className={custom.inputTitleLeft}>
              <Typography variant="subtitle1">Amount</Typography>
            </Box>
          </Box>
        </div>
        <div className={custom.subCard}>
          <Box display="flex">
            <Box flexGrow={1}>
              <Controller
                as={TextField}
                name="amount"
                control={control}
                label="Amount"
                variant="filled"
                color="secondary"
                fullWidth
                className={custom.input}
                defaultValue=""
              />
            </Box>
            <Box>
              <Button
                type="submit"
                className={custom.sendButton}
                variant="contained"
                color="primary"
              >
                Create
              </Button>
            </Box>
          </Box>
        </div>
        <div className={custom.inputLeft}>
          <Box display="flex">
            <Box flexGrow={6}>
              <Typography variant="subtitle1">
                (Optional) Add Backup IDs
              </Typography>
            </Box>
          </Box>
        </div>
        <div className={custom.inputLeft}>
          <Box display="flex">
            <Box flexGrow={6}>
              <Button
                type="button"
                className={custom.addButton}
                variant="contained"
                color="primary"
                onClick={() => {
                  append({ backupid: 'Backup ID' });
                }}
              >
                ADD
              </Button>
            </Box>
          </Box>
        </div>
        <div>
          <Box display="flex">
            <Box flexGrow={1} className={custom.inputDIDs}>
              <ul>
                {fields.map((item, index) => {
                  return (
                    <li key={item.id} style={{ listStyleType: 'none' }}>
                      <Controller
                        as={TextField}
                        name={`backup_dids[${index}].backupid`}
                        control={control}
                        defaultValue=""
                        label="Backup ID"
                        variant="filled"
                        color="secondary"
                        className={custom.inputDID}
                      />
                      <Button
                        type="button"
                        className={custom.sideButton}
                        variant="contained"
                        color="secondary"
                        disableElevation
                        onClick={() => remove(index)}
                      >
                        Delete
                      </Button>
                    </li>
                  );
                })}
              </ul>
            </Box>
          </Box>
        </div>
      </form>
      <Backdrop className={classes.backdrop} open={pending && created}>
        <CircularProgress color="inherit" />
      </Backdrop>
    </div>
  );
};
