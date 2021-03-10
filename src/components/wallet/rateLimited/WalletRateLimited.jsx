import React from 'react';
import Grid from '@material-ui/core/Grid';
import { makeStyles } from '@material-ui/core/styles';
import { useDispatch, useSelector } from 'react-redux';
import { Trans } from '@lingui/macro';
import Typography from '@material-ui/core/Typography';
import Box from '@material-ui/core/Box';
import TextField from '@material-ui/core/TextField';
import Button from '@material-ui/core/Button';
import Accordion from '@material-ui/core/Accordion';
import AccordionSummary from '@material-ui/core/AccordionSummary';
import AccordionDetails from '@material-ui/core/AccordionDetails';
import ExpandMoreIcon from '@material-ui/icons/ExpandMore';
import { Tooltip } from '@material-ui/core';
import HelpIcon from '@material-ui/icons/Help';
import { AlertDialog, Card, Flex } from '@chia/core';
import {
  send_transaction,
  rl_set_user_info_action,
} from '../../../modules/message';
import { mojo_to_chia_string, chia_to_mojo } from '../../../util/chia';
import { get_transaction_result } from '../../../util/transaction_result';
import { openDialog } from '../../../modules/dialog';
import WalletHistory from '../WalletHistory';
import useCurrencyCode from '../../../hooks/useCurrencyCode';

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
    color: '#3AAC59',
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
    height: 50,
  },
  clawbackButton: {
    marginTop: theme.spacing(2),
    marginBottom: theme.spacing(2),
    width: 200,
    height: 50,
  },
  copyButton: {
    marginTop: theme.spacing(0),
    marginBottom: theme.spacing(0),
    height: 56,
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
  submitButton: {
    marginTop: theme.spacing(2),
    marginBottom: theme.spacing(2),
    width: 150,
    height: 50,
  },
}));

const IncompleteCard = (props) => {
  const id = props.wallet_id;

  const dispatch = useDispatch();
  const data = useSelector((state) => state.wallet_state.wallets[id].data);
  const data_parsed = JSON.parse(data);
  const pubkey = data_parsed.user_pubkey;

  function copy() {
    navigator.clipboard.writeText(pubkey);
  }

  let ip_input = null;

  function submit() {
    const ip_val = ip_input.value;
    const hexcheck = /[\da-f]+$/gi;

    if (!hexcheck.test(ip_val) || ip_val.value === '') {
      dispatch(openDialog('Please enter a valid info packet'));
      return;
    }

    const ip_unhex = Buffer.from(ip_val, 'hex');
    const ip_debuf = ip_unhex.toString('utf8');
    const ip_parsed = JSON.parse(ip_debuf);
    const interval_input = ip_parsed.interval;
    const chiaper_input = ip_parsed.limit;
    const origin_input = ip_parsed.origin_string;
    const admin_pubkey_input = ip_parsed.admin_pubkey;
    const interval_value = Number.parseInt(Number(interval_input));
    const chiaper_value = Number.parseInt(Number(chiaper_input));
    const origin_parsed = JSON.parse(origin_input);
    dispatch(
      rl_set_user_info_action(
        id,
        interval_value,
        chiaper_value,
        origin_parsed,
        admin_pubkey_input,
      ),
    );
  }

  const classes = useStyles();
  return (
    <Card
      title={(
        <Trans>
          Rate Limited User Wallet Setup
        </Trans>
      )}
    >
      <Grid item xs={12}>
        <div className={classes.setupSection}>
          <Box display="flex">
            <Box flexGrow={1}>
              <Typography variant="subtitle1">
                <Trans>
                  Send your pubkey to your Rate Limited Wallet admin:
                </Trans>
              </Typography>
            </Box>
          </Box>
        </div>
      </Grid>
      <Grid item xs={12}>
        <Box display="flex">
          <Box flexGrow={1}>
            <TextField
              disabled
              fullWidth
              label={
                <Trans>User Pubkey</Trans>
              }
              value={pubkey}
              variant="outlined"
            />
          </Box>
          <Box>
            <Button
              onClick={copy}
              className={classes.copyButton}
              variant="contained"
              color="secondary"
              disableElevation
            >
              <Trans>Copy</Trans>
            </Button>
          </Box>
        </Box>
      </Grid>
      <Grid item xs={12}>
        <div className={classes.setupSection}>
          <Box display="flex">
            <Box flexGrow={1} style={{ marginTop: 10, marginBottom: 0 }}>
              <Typography variant="subtitle1">
                <Trans>
                  When you receive the setup info packet from your admin,
                  enter it below to complete your Rate Limited Wallet setup:
                </Trans>
              </Typography>
            </Box>
          </Box>
          <Box display="flex">
            <Box flexGrow={1} style={{ marginTop: 0 }}>
              <TextField
                variant="filled"
                color="secondary"
                fullWidth
                inputRef={(input) => {
                  ip_input = input;
                }}
                margin="normal"
                label={
                  <Trans>Info Packet</Trans>
                }
              />
            </Box>
          </Box>
        </div>
        <div className={classes.setupSection}>
          <Box display="flex">
            <Box>
              <Button
                onClick={submit}
                className={classes.submitButton}
                variant="contained"
                color="primary"
              >
                <Trans>Submit</Trans>
              </Button>
            </Box>
          </Box>
        </div>
      </Grid>
    </Card>
  );
};

const RLDetailsCard = (props) => {
  const id = props.wallet_id;

  const data = useSelector((state) => state.wallet_state.wallets[id].data);
  const data_parsed = JSON.parse(data);
  const { type } = data_parsed;
  const { user_pubkey } = data_parsed;
  const { admin_pubkey } = data_parsed;
  const { interval } = data_parsed;
  const { limit } = data_parsed;
  const origin = data_parsed.rl_origin;
  const origin_string = JSON.stringify(origin);
  const infopacket = {
    interval,
    limit,
    origin_string,
    admin_pubkey,
  };

  const ip_string = JSON.stringify(infopacket);
  const ip_buf = Buffer.from(ip_string, 'utf8');
  const ip_hex = ip_buf.toString('hex');

  function user_copy() {
    navigator.clipboard.writeText(user_pubkey);
  }

  function ip_hex_copy() {
    navigator.clipboard.writeText(ip_hex);
  }

  const classes = useStyles();
  if (type === 'user') {
    return (
      <Card
        title={<Trans>Rate Limited Info</Trans>}
      >
        <Grid item xs={12}>
          <Box display="flex">
            <Box flexGrow={1}>
              <Typography variant="subtitle1">
                <Trans>
                  Spending Interval (number of blocks): {interval}
                </Trans>
              </Typography>
            </Box>
            <Box flexGrow={1}>
              <Typography variant="subtitle1">
                <Trans>
                  Spending Limit (chia per interval):{' '}
                  {mojo_to_chia_string(limit)}
                </Trans>
              </Typography>
            </Box>
          </Box>
        </Grid>
        <Grid item xs={12}>
          <Box display="flex" style={{ marginBottom: 20 }}>
            <Box flexGrow={1}>
              <TextField
                disabled
                fullWidth
                label={<Trans>My Pubkey</Trans>}
                value={user_pubkey}
                variant="outlined"
              />
            </Box>
            <Box>
              <Button
                onClick={user_copy}
                className={classes.copyButton}
                variant="contained"
                color="secondary"
                disableElevation
              >
                <Trans>Copy</Trans>
              </Button>
            </Box>
          </Box>
        </Grid>
      </Card>
    );
  }
  if (type === 'admin') {
    return (
      <Card
        title={<Trans>Rate Limited Info</Trans>}
      >
        <Grid item xs={12}>
          <Box display="flex" style={{ marginBottom: 20, marginTop: 20 }}>
            <Box flexGrow={1}>
              <Typography variant="subtitle1">
                <Trans>
                  Spending Interval (number of blocks): {interval}
                </Trans>
              </Typography>
            </Box>
            <Box flexGrow={1}>
              <Typography variant="subtitle1">
                <Trans>
                  Spending Limit (chia per interval):{' '}
                  {mojo_to_chia_string(limit)}
                </Trans>
              </Typography>
            </Box>
          </Box>
        </Grid>
        <Grid item xs={12}>
          <Box display="flex">
            <Box flexGrow={1} style={{ marginTop: 5, marginBottom: 20 }}>
              <Typography variant="subtitle1">
                <Trans>
                  Send this info packet to your Rate Limited Wallet user who
                  must use it to complete setup of their wallet:
                </Trans>
              </Typography>
            </Box>
          </Box>
          <Box display="flex" style={{ marginBottom: 20 }}>
            <Box flexGrow={1}>
              <TextField
                disabled
                fullWidth
                label={
                  <Trans>Info Packet</Trans>
                }
                value={ip_hex}
                variant="outlined"
              />
            </Box>
            <Box>
              <Button
                onClick={ip_hex_copy}
                className={classes.copyButton}
                variant="contained"
                color="secondary"
                disableElevation
              >
                <Trans>Copy</Trans>
              </Button>
            </Box>
          </Box>
        </Grid>
      </Card>
    );
  }
};

const BalanceCardSubSection = (props) => {
  const currencyCode = useCurrencyCode();

  return (
    <Grid item xs={12}>
      <Box display="flex">
        <Box flexGrow={1}>
          <Typography variant="subtitle1">
            {props.title}
            {props.tooltip ? (
              <Tooltip title={props.tooltip}>
                <HelpIcon style={{ color: '#c8c8c8', fontSize: 12 }} />
              </Tooltip>
            ) : (
              ''
            )}
          </Typography>
        </Box>
        <Box>
          <Typography variant="subtitle1">
            {mojo_to_chia_string(props.balance)} {currencyCode}
          </Typography>
        </Box>
      </Box>
    </Grid>
  );
};

const BalanceCard = (props) => {
  const id = props.wallet_id;
  const balance = useSelector(
    (state) => state.wallet_state.wallets[id].balance_total,
  );
  const balance_spendable = useSelector(
    (state) => state.wallet_state.wallets[id].balance_spendable,
  );
  const balance_pending = useSelector(
    (state) => state.wallet_state.wallets[id].balance_pending,
  );
  const balance_change = useSelector(
    (state) => state.wallet_state.wallets[id].balance_change,
  );
  const balance_ptotal = balance + balance_pending;
  const classes = useStyles();

  return (
    <Card
      title={<Trans>Balance</Trans>}
    >
      <BalanceCardSubSection
        title={<Trans>Total Balance</Trans>}
        balance={balance}
        tooltip=""
      />
      <BalanceCardSubSection
        title={
          <Trans>Spendable Balance</Trans>
        }
        balance={balance_spendable}
        tooltip=""
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
                  <Trans>
                    View pending balances
                  </Trans>
                </Typography>
              </AccordionSummary>
              <AccordionDetails>
                <Grid container spacing={0}>
                  <BalanceCardSubSection
                    title={
                      <Trans>
                        Pending Total Balance
                      </Trans>
                    }
                    balance={balance_ptotal}
                    tooltip=""
                  />
                  <BalanceCardSubSection
                    title={
                      <Trans>
                        Pending Balance
                      </Trans>
                    }
                    balance={balance_pending}
                    tooltip=""
                  />
                  <BalanceCardSubSection
                    title={
                      <Trans>
                        Pending Change
                      </Trans>
                    }
                    balance={balance_change}
                    tooltip=""
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

const SendCard = (props) => {
  const id = props.wallet_id;
  const classes = useStyles();
  let address_input = null;
  let amount_input = null;
  let fee_input = null;
  const dispatch = useDispatch();

  const sending_transaction = useSelector(
    (state) => state.wallet_state.wallets[id].sending_transaction,
  );
  const syncing = useSelector((state) => state.wallet_state.status.syncing);

  const send_transaction_result = useSelector(
    (state) => state.wallet_state.wallets[id].send_transaction_result,
  );

  const result = get_transaction_result(send_transaction_result);
  const result_message = result.message;
  const result_class = result.success
    ? classes.resultSuccess
    : classes.resultFailure;

  function send() {
    if (sending_transaction) {
      return;
    }
    if (syncing) {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>
              Please finish syncing before making a transaction
            </Trans>
          </AlertDialog>
        ),
      );
      return;
    }
    let address = address_input.value.trim();
    if (
      amount_input.value === '' ||
      Number(amount_input.value) === 0 ||
      !Number(amount_input.value) ||
      isNaN(Number(amount_input.value))
    ) {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>
              Please enter a valid numeric amount
            </Trans>
          </AlertDialog>
        ),
      );
      return;
    }
    if (fee_input.value === '' || isNaN(Number(fee_input.value))) {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>
              Please enter a valid numeric fee
            </Trans>
          </AlertDialog>
        ),
      );
      return;
    }
    const amount = chia_to_mojo(amount_input.value);
    const fee = chia_to_mojo(fee_input.value);

    if (address.startsWith('0x') || address.startsWith('0X')) {
      address = address.slice(2);
    }

    const amount_value = Number.parseFloat(Number(amount));
    const fee_value = Number.parseFloat(Number(fee));
    if (fee_value !== 0) {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>
              Please enter 0 fee. Positive fees not supported yet for RL.
            </Trans>
          </AlertDialog>
        ),
      );
      return;
    }

    dispatch(send_transaction(id, amount_value, fee_value, address));
    address_input.value = '';
    amount_input.value = '';
    fee_input.value = '';
  }

  return (
    <Card
      title={<Trans>Create Transaction</Trans>}
    >
      {result_message && (
        <Grid item xs={12}>
          <p className={result_class}>{result_message}</p>
        </Grid>
      )}
      <Grid item xs={12}>
        <Box display="flex">
          <Box flexGrow={1}>
            <TextField
              variant="filled"
              color="secondary"
              fullWidth
              disabled={sending_transaction}
              inputRef={(input) => {
                address_input = input;
              }}
              label={
                <Trans>
                  Address / Puzzle hash
                </Trans>
              }
            />
          </Box>
          <Box />
        </Box>
      </Grid>
      <Grid item xs={12}>
        <Box display="flex">
          <Box flexGrow={6}>
            <TextField
              variant="filled"
              color="secondary"
              fullWidth
              disabled={sending_transaction}
              className={classes.leftField}
              margin="normal"
              inputRef={(input) => {
                amount_input = input;
              }}
              label={<Trans>Amount</Trans>}
            />
          </Box>
          <Box flexGrow={6}>
            <TextField
              variant="filled"
              fullWidth
              color="secondary"
              margin="normal"
              disabled={sending_transaction}
              inputRef={(input) => {
                fee_input = input;
              }}
              label={<Trans>Fee</Trans>}
            />
          </Box>
        </Box>
      </Grid>
      <Grid item xs={12}>
        <Box display="flex">
          <Box>
            <Button
              onClick={send}
              className={classes.sendButton}
              variant="contained"
              color="primary"
              disabled={sending_transaction}
            >
              <Trans>Send</Trans>
            </Button>
          </Box>
        </Box>
      </Grid>
    </Card>
  );
};

export default function RateLimitedWallet(props) {
  const id = useSelector((state) => state.wallet_menu.id);
  const wallets = useSelector((state) => state.wallet_state.wallets);
  const data = useSelector((state) => state.wallet_state.wallets[id].data);
  const data_parsed = JSON.parse(data);
  const { type } = data_parsed;
  const initStatus = data_parsed.initialized;

  if (wallets.length > props.wallet_id) {
    if (type === 'user') {
      if (initStatus) {
        return (
          <Flex flexDirection="column" gap={3}>
            <RLDetailsCard wallet_id={id} />
            <BalanceCard wallet_id={id} />
            <SendCard wallet_id={id} />
            <WalletHistory walletId={id} />
          </Flex>
        );
      }
      return (
        <Flex flexDirection="column" gap={3}>
          <IncompleteCard wallet_id={id} />
        </Flex>
      );
    }
    if (type === 'admin') {
      return (
        <Flex flexDirection="column" gap={3}>
          <RLDetailsCard wallet_id={id} />
          <BalanceCard wallet_id={id} />
        </Flex>
      );
    }
  }

  return null;
}
