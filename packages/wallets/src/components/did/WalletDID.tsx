import React, { useEffect, useState } from 'react';
import Grid from '@material-ui/core/Grid';
import { Alert } from '@material-ui/lab';
import { makeStyles } from '@material-ui/core/styles';
import { useDispatch, useSelector } from 'react-redux';
import { Trans } from '@lingui/macro';
import { Backup as BackupIcon } from '@material-ui/icons';
import Typography from '@material-ui/core/Typography';
import Paper from '@material-ui/core/Paper';
import Box from '@material-ui/core/Box';
import TextField from '@material-ui/core/TextField';
import Button from '@material-ui/core/Button';
import Backdrop from '@material-ui/core/Backdrop';
import CircularProgress from '@material-ui/core/CircularProgress';
import { AlertDialog, Card, Flex, Loading, Dropzone, mojoToChiaLocaleString } from '@chia/core';
import {
  did_generate_backup_file,
  did_spend,
  did_update_recovery_ids_action,
  did_create_attest,
  did_recovery_spend_action,
  did_get_recovery_info
} from '../../../modules/message';
import {
  Accordion,
  AccordionSummary,
  AccordionDetails,
} from '@material-ui/core';
import ExpandMoreIcon from '@material-ui/icons/ExpandMore';
import { Tooltip } from '@material-ui/core';
import HelpIcon from '@material-ui/icons/Help';
import { useForm, Controller, useFieldArray } from 'react-hook-form';
import { openDialog } from '../../../modules/dialog';
import useCurrencyCode from '../../../hooks/useCurrencyCode';
import WalletHistory from '../WalletHistory';
import useWallet from '../../../hooks/useWallet';

const drawerWidth = 240;

const useStyles = makeStyles((theme) => ({
  front: {
    zIndex: '100',
  },
  root: {
    display: 'flex',
    paddingLeft: '0px',
  },
  resultSuccess: {
    color: 'green',
  },
  resultFailure: {
    color: 'red',
  },
  toolbar: {
    paddingRight: 24, // keep right padding when drawer closed
  },
  toolbarIcon: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'flex-end',
    padding: '0 8px',
    ...theme.mixins.toolbar,
  },
  appBar: {
    zIndex: theme.zIndex.drawer + 1,
    transition: theme.transitions.create(['width', 'margin'], {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.leavingScreen,
    }),
  },
  appBarShift: {
    marginLeft: drawerWidth,
    width: `calc(100% - ${drawerWidth}px)`,
    transition: theme.transitions.create(['width', 'margin'], {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.enteringScreen,
    }),
  },
  menuButton: {
    marginRight: 36,
  },
  menuButtonHidden: {
    display: 'none',
  },
  title: {
    flexGrow: 1,
  },
  drawerPaper: {
    position: 'relative',
    whiteSpace: 'nowrap',
    width: drawerWidth,
    transition: theme.transitions.create('width', {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.enteringScreen,
    }),
  },
  drawerPaperClose: {
    overflowX: 'hidden',
    transition: theme.transitions.create('width', {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.leavingScreen,
    }),
    width: theme.spacing(7),
    [theme.breakpoints.up('sm')]: {
      width: theme.spacing(9),
    },
  },
  appBarSpacer: theme.mixins.toolbar,
  content: {
    flexGrow: 1,
    height: '100vh',
    overflow: 'auto',
  },
  container: {
    paddingTop: theme.spacing(0),
    paddingBottom: theme.spacing(0),
    paddingRight: theme.spacing(0),
  },
  paper: {
    marginTop: theme.spacing(2),
    padding: theme.spacing(2),
    display: 'flex',
    overflow: 'auto',
    flexDirection: 'column',
  },
  drawerWallet: {
    position: 'relative',
    whiteSpace: 'nowrap',
    width: drawerWidth,
    height: '100%',
    transition: theme.transitions.create('width', {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.enteringScreen,
    }),
  },
  balancePaper: {
    marginTop: theme.spacing(2),
  },
  sendButton: {
    marginTop: theme.spacing(2),
    marginBottom: theme.spacing(2),
    width: 150,
    height: 56,
  },
  submitButton: {
    marginLeft: theme.spacing(3),
    marginRight: theme.spacing(2),
    height: 56,
    width: 150,
  },
  sendButtonSide: {
    marginLeft: theme.spacing(3),
    height: 56,
    width: 150,
  },
  copyButton: {
    marginTop: theme.spacing(0),
    marginBottom: theme.spacing(0),
    width: 70,
    height: 56,
  },
  subCard: {
    height: 100,
  },
  cardTitle: {
    paddingLeft: theme.spacing(1),
    paddingTop: theme.spacing(1),
    marginBottom: theme.spacing(1),
  },
  cardSubSection: {
    paddingLeft: theme.spacing(3),
    paddingRight: theme.spacing(3),
    paddingTop: theme.spacing(1),
  },
  setupSection: {
    paddingLeft: theme.spacing(3),
    paddingRight: theme.spacing(3),
    paddingTop: theme.spacing(3),
    paddingBottom: theme.spacing(1),
  },
  setupTitle: {
    paddingLeft: theme.spacing(3),
    paddingRight: theme.spacing(3),
    paddingTop: theme.spacing(2),
    paddingBottom: theme.spacing(0),
  },
  input: {
    height: 56,
  },
  inputLeft: {
    marginLeft: theme.spacing(3),
    height: 56,
  },
  inputRight: {
    marginRight: theme.spacing(3),
    marginLeft: theme.spacing(6),
    height: 56,
  },
  inputTitleLeft: {
    marginLeft: theme.spacing(0),
    marginBottom: theme.spacing(0),
    width: 400,
  },
  inputTitleRight: {
    marginLeft: theme.spacing(3),
    width: 400,
  },
  updateDIDsTitle: {
    marginTop: theme.spacing(3),
  },
  inputDID: {
    marginTop: theme.spacing(1),
    marginLeft: theme.spacing(-5),
    marginBottom: theme.spacing(2),
  },
  walletContainer: {
    marginBottom: theme.spacing(5),
  },
  table_root: {
    width: '100%',
    maxHeight: 600,
    overflowY: 'scroll',
    padding: theme.spacing(1),
    margin: theme.spacing(1),
    marginBottom: theme.spacing(2),
    marginTop: theme.spacing(2),
    display: 'flex',
    overflow: 'auto',
    flexDirection: 'column',
  },
  table: {
    height: '100%',
    overflowY: 'scroll',
  },
  tableBody: {
    height: '100%',
    overflowY: 'scroll',
  },
  row: {
    width: 700,
  },
  cell_short: {
    fontSize: '14px',
    width: 50,
    overflowWrap: 'break-word' /* Renamed property in CSS3 draft spec */,
  },
  leftField: {
    paddingRight: 20,
  },
  ul: {
    listStyle: 'none',
  },
  addButton: {
    marginTop: theme.spacing(2),
    marginBottom: theme.spacing(2),
    height: 56,
    width: 50,
  },
  sideButton: {
    marginTop: theme.spacing(1),
    marginBottom: theme.spacing(0),
    height: 56,
  },
  addText: {
    marginTop: theme.spacing(3),
    marginBottom: theme.spacing(2),
  },
  addIDsText: {
    marginTop: theme.spacing(4),
    marginBottom: theme.spacing(1),
  },
  addID: {
    height: 56,
    marginBottom: theme.spacing(0),
    marginTop: theme.spacing(1),
    paddingRight: theme.spacing(2),
  },
  deleteButton: {
    marginLeft: theme.spacing(2),
    width: 75,
    height: 30,
  },
  packetWaitText: {
    height: 30,
  },
}));

const RecoveryCard = (props) => {
  const id = props.wallet_id;
  const { wallet } = useWallet(id);

  const { 
    mydid, 
    didcoin, 
    did_rec_pubkey, 
    did_rec_puzhash, 
    backup_dids: backup_did_list,
    dids_num_req,
  } = wallet;

  const dispatch = useDispatch();

  const [files, setFiles] = useState([]);

  function handleRemoveFile(event, name) {
    event.stopPropagation();
    event.preventDefault();

    setFiles(files.filter((object) => object !== name));
  }

  function handleDrop(acceptedFiles) {
    const newFiles = [...files];

    acceptedFiles.forEach((file) => {
      newFiles.push(file.path);
    });

    setFiles(newFiles);
  }

  function submit() {
    if (files.length < dids_num_req) {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>Your DID requires at least {dids_num_req} attestation file{dids_num_req === 1 ? "" : "s"} for recovery. Please upload additional files.</Trans>
          </AlertDialog>
        ),
      );
      return;
    } else {
      dispatch(did_recovery_spend_action(id, files));
    }
  }

  return (
    <Flex flexDirection="column" gap={2}>
      <Card title={<Trans>Recover DID Wallet</Trans>}>
        <Grid item xs={12}>
          <Box display="flex">
            <Box flexGrow={1} style={{ marginBottom: 20 }}>
              <Flex gap={1} alignItems="center">
                <Typography variant="subtitle1">Recovery Information</Typography>
                <Tooltip title="Send your DID's coin name, pubkey, and puzzlehash to your Backup ID(s) so that they may create an attestation packet.">
                  <HelpIcon style={{ color: '#c8c8c8', fontSize: 12 }} />
                </Tooltip>
              </Flex>
            </Box>
          </Box>
          <Box display="flex">
            <Box flexGrow={1}>
              <Typography variant="subtitle1">My DID:</Typography>
            </Box>
            <Box
              style={{
                width: '85%',
                overflowWrap: 'break-word',
                marginBottom: 20,
              }}
            >
              <Typography variant="subtitle1">{mydid}</Typography>
            </Box>
          </Box>
          <Box display="flex">
            <Box flexGrow={1}>
              <Typography variant="subtitle1">Coin Name:</Typography>
            </Box>
            <Box
              style={{
                width: '85%',
                overflowWrap: 'break-word',
                marginBottom: 20,
              }}
            >
              <Typography variant="subtitle1">{didcoin}</Typography>
            </Box>
          </Box>
          <Box display="flex">
            <Box flexGrow={1}>
              <Typography variant="subtitle1">Pubkey:</Typography>
            </Box>
            <Box
              style={{
                width: '85%',
                overflowWrap: 'break-word',
                marginBottom: 20,
              }}
            >
              <Typography variant="subtitle1">{did_rec_pubkey}</Typography>
            </Box>
          </Box>
          <Box display="flex">
            <Box flexGrow={1}>
              <Typography variant="subtitle1">Puzzlehash:</Typography>
            </Box>
            <Box
              style={{
                width: '85%',
                overflowWrap: 'break-word',
                marginBottom: 20,
              }}
            >
              <Typography variant="subtitle1">{did_rec_puzhash}</Typography>
            </Box>
          </Box>
        </Grid>
        <ViewDIDsSubsection
          backup_did_list={backup_did_list}
          dids_num_req={dids_num_req}
        />
        <Grid item xs={12}>
          <Box display="flex">
            <Box flexGrow={1} style={{ marginTop: 30 }}>
              <Typography variant="subtitle1">
                Input Attestation Packet(s)
              </Typography>
            </Box>
          </Box>
        </Grid>
        <Grid item xs={12}>
          <Dropzone onDrop={handleDrop}>
            {!files.length ? (
              <Flex flexDirection="column" gap={2} alignItems="center">
                <BackupIcon fontSize="large" />
                <Typography variant="body2" align="center">
                  <Trans>
                    Drag and drop attestation packet(s)
                  </Trans>
                </Typography>
              </Flex>
            ) : (
              <Flex flexDirection="column" gap={2}>
                <Typography variant="subtitle1">
                  Attestation Packet(s):
                </Typography>
                {files.map((object, index) => (
                  <Flex flexBasis={0} key={index} gap={1} alignItems="center">
                    <Flex flexGrow={1} flexBasis={0}>
                      <Typography variant="body2" noWrap>
                        {object}
                      </Typography>
                    </Flex>
                    <Button
                      onClick={(event) => handleRemoveFile(event, object)}
                      variant="contained"
                    >
                      <Trans>Delete</Trans>
                    </Button>
                  </Flex>
                ))}
              </Flex>
            )}
          </Dropzone>
        </Grid>
      </Card>
      <Box>
        <Button
          onClick={submit}
          variant="contained"
          color="primary"
        >
          <Trans>Recover</Trans>
        </Button>
      </Box>
    </Flex>
  );
};

const RecoveryTransCard = (props) => {
  const id = props.wallet_id;
  const { wallet } = useWallet(id);
  const { mydid, data } = wallet;
  const data_parsed = JSON.parse(data);
  const temp_coin = data_parsed.temp_coin;
  const classes = useStyles();

  return (
    <Card title={<Trans>Recover DID Wallet</Trans>}>
      <Grid item xs={12}>
        <div className={classes.cardSubSection}>
          <Box display="flex" style={{ marginTop: 20, marginBottom: 20 }}>
            <Box flexGrow={1}>
              <Typography variant="subtitle1">My DID:</Typography>
            </Box>
            <Box
              style={{
                width: '85%',
                overflowWrap: 'break-word',
              }}
            >
              <Typography variant="subtitle1">{mydid}</Typography>
            </Box>
          </Box>
          <Box display="flex">
            <Box flexGrow={1} style={{ marginTop: 20, marginBottom: 20 }}>
              <Flex alignItems="stretch">
                <Typography variant="subtitle1">Your DID wallet recovery is in progress. Please check back soon.</Typography>
                <Tooltip title="The DID recovery process usually resolves after the addition of a few blockheights.">
                  <HelpIcon style={{ color: '#c8c8c8', fontSize: 12 }} />
                </Tooltip>
              </Flex>
            </Box>
          </Box>
        </div>
      </Grid>
    </Card>
  );
};

const MyDIDCard = (props) => {
  const id = props.wallet_id;
  const { wallet } = useWallet(id);
  const { mydid } = wallet;
  let filename_input = null;
  const classes = useStyles();
  const dispatch = useDispatch();

  const generateBackup = () => {
    const filename = filename_input.value;
    if (filename === '') {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>Please enter a filename</Trans>
          </AlertDialog>
        ),
      );
      return;
    };
    dispatch(did_generate_backup_file(id, filename));
    filename_input.value = '';
  };

  return (
    <Card title={<Trans>My DID Wallet</Trans>}>
      <Grid item xs={12}>
        <Box display="flex">
          <Box flexGrow={1}>
            <Typography variant="subtitle1">My DID:</Typography>
          </Box>
          <Box
            style={{
              width: '85%',
              overflowWrap: 'break-word',
            }}
          >
            <Typography variant="subtitle1">{mydid}</Typography>
          </Box>
        </Box>
      </Grid>
      <Grid item xs={12}>
        <Box display="flex">
          <Box
            flexGrow={6}
            className={classes.inputTitleLeft}
            style={{ marginBottom: 10 }}
          >
            <Typography variant="subtitle1">
              Create a backup file:
            </Typography>
          </Box>
        </Box>
        <Box display="flex">
          <Box flexGrow={1}>
            <TextField
              className={classes.input}
              variant="filled"
              color="secondary"
              fullWidth
              inputRef={(input) => {
                filename_input = input;
              }}
              label="Filename"
            />
          </Box>
          <Box>
            <Button
              onClick={generateBackup}
              className={classes.sendButtonSide}
              variant="contained"
              color="primary"
            >
              Create
            </Button>
          </Box>
        </Box>
      </Grid>
    </Card>
  );
};

const BalanceCardSubSection = (props) => {
  const currencyCode = useCurrencyCode();
  const classes = useStyles();
  return (
    <Grid item xs={12}>
      <Box display="flex">
        <Box flexGrow={1}>
          <Typography variant="subtitle1">
            {props.title}
            {props.tooltip ? (
              <Tooltip title={props.tooltip}>
                <HelpIcon
                  style={{ color: '#c8c8c8', fontSize: 12 }}
                ></HelpIcon>
              </Tooltip>
            ) : (
              ''
            )}
          </Typography>
        </Box>
        <Box>
          <Typography variant="subtitle1">
            {mojoToChiaLocaleString(props.balance)} TXCH
          </Typography>
        </Box>
      </Box>
    </Grid>
  );
};

const BalanceCard = (props) => {
  const id = props.wallet_id;

  const classes = useStyles();
  const { wallet, loading } = useWallet(id);
  if (loading || !wallet.wallet_balance) {
    return (
      <Loading center />
    );
  }

  const {
    wallet_balance: {
      confirmed_wallet_balance: balance,
      balance_spendable,
      balance_pending,
      balance_change,
    },
  } = wallet;

  const balance_ptotal = balance + balance_pending;

  return (
    <Card title={<Trans>Balance</Trans>}>
      <BalanceCardSubSection
        title="Total Balance"
        balance={balance}
        tooltip=""
      />
      <BalanceCardSubSection
        title="Spendable Balance"
        balance={balance_spendable}
        tooltip={''}
      />
      <Grid item xs={12}>
        <Box display="flex">
          <Box flexGrow={1}>
            <Accordion className={classes.front}>
              <AccordionSummary
                expandIcon={<ExpandMoreIcon />}
                aria-controls="panel1a-content"
                id="panel1a-header"
              >
                <Typography className={classes.heading}>
                  View pending balances
                </Typography>
              </AccordionSummary>
              <AccordionDetails>
                <Grid container spacing={0}>
                  <BalanceCardSubSection
                    title="Pending Total Balance"
                    balance={balance_ptotal}
                    tooltip={''}
                  />
                  <BalanceCardSubSection
                    title="Pending Balance"
                    balance={balance_pending}
                    tooltip={''}
                  />
                  <BalanceCardSubSection
                    title="Pending Change"
                    balance={balance_change}
                    tooltip={''}
                  />
                </Grid>
              </AccordionDetails>
            </Accordion>
          </Box>
        </Box>
      </Grid>
    </Card>
  );
};

const ViewDIDsSubsection = (props) => {
  const classes = useStyles();
  const backup_list = props.backup_did_list;
  const dids_num_req = props.dids_num_req;
  const isEmptyList = !backup_list || !backup_list.length;

  return (
    <Grid item xs={12}>
      <Box display="flex">
        <Box flexGrow={1}>
          <Accordion className={classes.front}>
            <AccordionSummary
              expandIcon={<ExpandMoreIcon />}
              aria-controls="panel1a-content"
              id="panel1a-header"
            >
              <Typography className={classes.heading}>
                View your list of Backup IDs ({dids_num_req} Backup ID{dids_num_req === 1 ? " is " : "s are "} required for recovery)
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Grid item xs={12}>
                <div className={classes.cardSubSection}>
                  <Box display="flex">
                    <Box flexGrow={1}>
                      <Typography variant="subtitle1">
                        {isEmptyList
                          ? 'Your backup list is currently empty.'
                          : backup_list.map((object, i) => (
                            <span key={i}>
                              <Typography variant="subtitle1">
                                &#8226; {object}
                              </Typography>
                            </span>
                          ))}
                      </Typography>
                    </Box>
                  </Box>
                </div>
              </Grid>
            </AccordionDetails>
          </Accordion>
        </Box>
      </Box>
    </Grid>
  );
};

const ManageDIDsCard = (props) => {
  const id = props.wallet_id;
  const classes = useStyles();
  const dispatch = useDispatch();
  const pending = useSelector((state) => state.create_options.pending);
  const created = useSelector((state) => state.create_options.created);

  const { wallet } = useWallet(id);
  const { 
    backup_dids: backup_did_list,
    dids_num_req
  } = wallet;

  const { handleSubmit, control } = useForm();
  const { fields, append, remove } = useFieldArray({
    control,
    name: 'backup_dids',
  });

  const onSubmit = (data) => {
    const didArray = data.backup_dids?.map((item) => item.backupid) ?? [];
    let uniqDidArray = Array.from(new Set(didArray));
    uniqDidArray = uniqDidArray.filter(item => item !== "")
    const num_of_backup_ids_needed = data.num_needed;
    if (
      num_of_backup_ids_needed === '' ||
      isNaN(Number(num_of_backup_ids_needed))
    ) {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>Please enter a valid integer of 0 or greater for the number of Backup IDs needed for recovery.</Trans>
          </AlertDialog>
        ),
      );
      return;
    }
    if (
      num_of_backup_ids_needed > uniqDidArray.length
    )
    {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>The number of Backup IDs needed for recovery cannot exceed the number of Backup IDs added.</Trans>
          </AlertDialog>
        ),
      );
      return;
    }
    dispatch(
      did_update_recovery_ids_action(
        id,
        uniqDidArray,
        num_of_backup_ids_needed,
      ),
    );
  };

  return (
    <Card title={<Trans>Manage Recovery DIDs</Trans>}>
      <ViewDIDsSubsection
        backup_did_list={backup_did_list}
        dids_num_req={dids_num_req}
      />
      <Grid item xs={12}>
        <form onSubmit={handleSubmit(onSubmit)}>
          <Flex flexDirection="column" gap={3}>
            <Flex flexDirection="column" gap={1}>
              <Flex alignItems="center" gap={1}>
                <Typography variant="subtitle1">
                  Update number of Backup IDs needed for recovery
                </Typography>
                <Tooltip title="This number must be greater than or equal to 0, and it may not exceed the number of Backup IDs you have added. You will be able to change this number as well as your list of Backup IDs.">
                  <HelpIcon style={{ color: '#c8c8c8', fontSize: 12 }} />
                </Tooltip>
              </Flex>
              <Controller
                as={TextField}
                name="num_needed"
                control={control}
                label="Number of Backup IDs needed for recovery"
                variant="outlined"
                fullWidth
                defaultValue=""
              />
            </Flex>
              
            <Flex flexDirection="column" gap={1}>
              <Flex alignItems="center" gap={1}>
                <Typography variant="subtitle1">
                  Update Backup IDs
                </Typography>
                <Tooltip title="Please enter a new set of recovery IDs. Be sure to re-enter any current recovery IDs which you would like to keep in your recovery list.">
                  <HelpIcon style={{ color: '#c8c8c8', fontSize: 12 }} />
                </Tooltip>
              </Flex>
              {fields.map((item, index) => (
                <Flex alignItems="stretch">
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
                    disableElevation
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
                  variant="contained"
                  disableElevation
                >
                  <Trans>Add Backup ID</Trans>
                </Button>
              </Box>
            </Flex>

            <Box>
              <Button
                type="submit"
                variant="contained"
                color="primary"
                disableElevation
              >
                <Trans>Submit</Trans>
              </Button>
            </Box>
          </Flex>
        </form>
      </Grid>
      {pending && created && (
        <Backdrop className={classes.backdrop} open={pending && created}>
          <CircularProgress color="inherit" />
        </Backdrop>
      )}
    </Card>
  );
};

const CreateAttest = (props) => {
  const id = props.wallet_id;
  let filename_input = null;
  let coin_input = null;
  let pubkey_input = null;
  let puzhash_input = null;
  const dispatch = useDispatch();

  function createAttestPacket() {
    if (filename_input.value === '') {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>Please enter a filename</Trans>
          </AlertDialog>
        ),
      );
      return;
    }
    if (coin_input.value === '') {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>Please enter a coin</Trans>
          </AlertDialog>
        ),
      );
      return;
    }
    if (pubkey_input.value === '') {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>Please enter a pubkey</Trans>
          </AlertDialog>
        ),
      );
      return;
    }
    if (puzhash_input.value === '') {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>Please enter a puzzlehash</Trans>
          </AlertDialog>
        ),
      );
      return;
    }
    let address = puzhash_input.value.trim();
    if (address.substring(0, 12) === 'chia_addr://') {
      address = address.substring(12);
    }
    if (address.startsWith('0x') || address.startsWith('0X')) {
      address = address.substring(2);
    }

    dispatch(did_create_attest(id, filename_input.value, coin_input.value, pubkey_input.value, address));

    filename_input.value = '';
    coin_input.value = '';
    pubkey_input.value = '';
    puzhash_input.value = '';
  }

  return (
    <Card title={<Trans>Create An Attestation Packet</Trans>}>
      <TextField
        variant="filled"
        color="secondary"
        fullWidth
        inputRef={(input) => {
          filename_input = input;
        }}
        label={<Trans>Filename</Trans>}
      />
      <TextField
        variant="filled"
        color="secondary"
        fullWidth
        inputRef={(input) => {
          coin_input = input;
        }}
        label={<Trans>Coin Name</Trans>}
      />
      <TextField
        variant="filled"
        color="secondary"
        fullWidth
        inputRef={(input) => {
          pubkey_input = input;
        }}
        label={<Trans>Pubkey</Trans>}
      />
      <TextField
        variant="filled"
        color="secondary"
        fullWidth
        inputRef={(input) => {
          puzhash_input = input;
        }}
        label={<Trans>Puzzlehash</Trans>}
      />
      <Box>
        <Button
          onClick={createAttestPacket}
          variant="contained"
          color="primary"
        >
          Create
        </Button>
      </Box>
    </Card>
  );
};

// this is currently not being displayed; did_spend does not exist in wallet_rpc_api.py
const CashoutCard = (props) => {
  const id = props.wallet_id;
  let address_input = null;
  const classes = useStyles();
  const dispatch = useDispatch();

  function cashout() {
    let puzzlehash = address_input.value.trim();

    if (puzzlehash.slice(0, 12) === 'chia_addr://') {
      puzzlehash = puzzlehash.slice(12);
    }
    if (puzzlehash.startsWith('0x') || puzzlehash.startsWith('0X')) {
      puzzlehash = puzzlehash.slice(2);
    }

    dispatch(did_spend(id, puzzlehash));
    address_input.value = '';
  }

  return (
    <Paper className={classes.paper}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              Cash Out
            </Typography>
          </div>
        </Grid>
        <Grid item xs={12}>
          <div className={classes.cardSubSection}>
            <Box display="flex">
              <Box flexGrow={1}>
                <TextField
                  variant="filled"
                  color="secondary"
                  fullWidth
                  inputRef={(input) => {
                    address_input = input;
                  }}
                  label="Address / Puzzle hash"
                />
              </Box>
              <Box></Box>
            </Box>
          </div>
        </Grid>
        <Grid item xs={12}>
          <div className={classes.cardSubSection}>
            <Box display="flex">
              <Box>
                <Button
                  onClick={cashout}
                  className={classes.sendButton}
                  variant="contained"
                  color="primary"
                >
                  Cash Out
                </Button>
              </Box>
            </Box>
          </div>
        </Grid>
      </Grid>
    </Paper>
  );
};

type Props = {
  walletId: number;
};

export default function WalletDID(props: Props) {
  const { walletId } = props;
  const dispatch = useDispatch();
  const { wallet, loading } = useWallet(walletId);

  useEffect(() => {
    if (wallet && wallet.data) {
      const {
        temp_coin: tempCoin,
        sent_recovery_transaction: sentRecoveryTransaction,
      } = JSON.parse(wallet.data);

      if (tempCoin && !sentRecoveryTransaction) {
        dispatch(did_get_recovery_info(walletId));
      }
    }
  }, [wallet, dispatch, walletId]);

  if (loading) {
    return (
      <Loading />
    );
  }

  if (!wallet) {
    return (
      <Alert severity="error">
        <Trans>Wallet does not exists</Trans>
      </Alert>
    );
  }

  const { data } = wallet;
  const {
    temp_coin: tempCoin,
    sent_recovery_transaction: sentRecoveryTransaction,
  } = JSON.parse(data);

  if (tempCoin) {
    if (sentRecoveryTransaction) {
      return (
        <Flex flexDirection="column" gap={3}>
          <RecoveryTransCard wallet_id={walletId} />
        </Flex>
      );
    }

    return (
      <Flex flexDirection="column" gap={3}>
        <RecoveryCard wallet_id={walletId} />
      </Flex>
    );
  }

  return (
    <Flex flexDirection="column" gap={3}>
      <MyDIDCard wallet_id={walletId} />
      <BalanceCard wallet_id={walletId} />
      <ManageDIDsCard wallet_id={walletId} />
      <CreateAttest wallet_id={walletId} />
      <WalletHistory walletId={walletId} />
    </Flex>
  );
}
