import React, { ReactNode } from 'react';
import { Trans } from '@lingui/macro';
import Grid from '@material-ui/core/Grid';
import { AlertDialog, Flex, Card } from '@chia/core';
import { makeStyles } from '@material-ui/core/styles';
import { useDispatch, useSelector } from 'react-redux';
import {
  Tooltip,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Box,
  Typography,
  Button,
  TextField,
} from '@material-ui/core';
import {
  ExpandMore as ExpandMoreIcon,
  Help as HelpIcon,
} from '@material-ui/icons';
import {
  get_address,
  send_transaction,
  farm_block,
} from '../../../modules/message';
import { mojo_to_chia_string, chia_to_mojo } from '../../../util/chia';
import { openDialog } from '../../../modules/dialog';
import { get_transaction_result } from '../../../util/transaction_result';
import config from '../../../config/config';
import type { RootState } from '../../../modules/rootReducer';
import WalletHistory from '../WalletHistory';
import useCurrencyCode from '../../../hooks/useCurrencyCode';

const drawerWidth = 240;

const useStyles = makeStyles((theme) => ({
  front: {
    zIndex: 100,
  },
  resultSuccess: {
    color: '#3AAC59',
  },
  resultFailure: {
    color: 'red',
  },
  root: {
    display: 'flex',
    paddingLeft: '0px',
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
  fixedHeight: {
    height: 240,
  },
  heading: {
    fontSize: theme.typography.pxToRem(15),
    fontWeight: theme.typography.fontWeightRegular,
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
  sendCard: {
    marginTop: theme.spacing(2),
  },
  sendButton: {
    marginTop: theme.spacing(2),
    marginBottom: theme.spacing(2),
    width: 150,
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
  walletContainer: {
    marginBottom: theme.spacing(5),
  },
  table_root: {
    width: '100%',
    maxHeight: 600,
    overflowY: 'scroll',
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
  amountField: {
    paddingRight: 20,
  },
}));

type BalanceCardSubSectionProps = {
  title: ReactNode;
  tooltip?: ReactNode;
  balance: number;
};

function BalanceCardSubSection(props: BalanceCardSubSectionProps) {
  const currencyCode = useCurrencyCode();

  return (
    <Grid item xs={12}>
      <Box display="flex">
        <Box flexGrow={1}>
          <Typography variant="subtitle1">
            {props.title}
            {props.tooltip && (
              <Tooltip title={props.tooltip}>
                <HelpIcon style={{ color: '#c8c8c8', fontSize: 12 }} />
              </Tooltip>
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
}

type BalanceCardProps = {
  wallet_id: number;
};

function BalanceCard(props: BalanceCardProps) {
  const id = props.wallet_id;
  const balance = useSelector(
    (state: RootState) => state.wallet_state.wallets[id].balance_total,
  );
  const balance_spendable = useSelector(
    (state: RootState) => state.wallet_state.wallets[id].balance_spendable,
  );
  const balance_pending = useSelector(
    (state: RootState) => state.wallet_state.wallets[id].balance_pending,
  );

  const balance_change = useSelector(
    (state: RootState) => state.wallet_state.wallets[id].balance_change,
  );
  const balance_ptotal = balance + balance_pending;
  const classes = useStyles();

  return (
    <Card title={<Trans>Balance</Trans>}>
      <BalanceCardSubSection
        title={<Trans>Total Balance</Trans>}
        balance={balance}
        tooltip={
          <Trans>
            This is the total amount of chia in the blockchain at the current
            peak sub block that is controlled by your private keys. It includes
            frozen farming rewards, but not pending incoming and outgoing
            transactions.
          </Trans>
        }
      />
      <BalanceCardSubSection
        title={<Trans>Spendable Balance</Trans>}
        balance={balance_spendable}
        tooltip={
          <Trans>
            This is the amount of Chia that you can currently use to make
            transactions. It does not include pending farming rewards, pending
            incoming transactions, and Chia that you have just spent but is not
            yet in the blockchain.
          </Trans>
        }
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
                  <Trans>View pending balances</Trans>
                </Typography>
              </AccordionSummary>
              <AccordionDetails>
                <Grid container spacing={0}>
                  <BalanceCardSubSection
                    title={<Trans>Pending Total Balance</Trans>}
                    balance={balance_ptotal}
                    tooltip={
                      <Trans>
                        This is the total balance + pending balance: it is what
                        your balance will be after all pending transactions are
                        confirmed.
                      </Trans>
                    }
                  />
                  <BalanceCardSubSection
                    title={<Trans>Pending Balance</Trans>}
                    balance={balance_pending}
                    tooltip={
                      <Trans>
                        This is the sum of the incoming and outgoing pending
                        transactions (not yet included into the blockchain).
                        This does not include farming rewards.
                      </Trans>
                    }
                  />
                  <BalanceCardSubSection
                    title={<Trans>Pending Change</Trans>}
                    balance={balance_change}
                    tooltip={
                      <Trans>
                        This is the pending change, which are change coins which
                        you have sent to yourself, but have not been confirmed
                        yet.
                      </Trans>
                    }
                  />
                </Grid>
              </AccordionDetails>
            </Accordion>
          </Box>
        </Box>
      </Grid>
    </Card>
  );
}

type SendCardProps = {
  wallet_id: number;
};

function SendCard(props: SendCardProps) {
  const id = props.wallet_id;
  const classes = useStyles();
  let address_input: HTMLInputElement;
  let amount_input: HTMLInputElement;
  let fee_input: HTMLInputElement;
  const dispatch = useDispatch();

  const sending_transaction = useSelector(
    (state: RootState) => state.wallet_state.wallets[id].sending_transaction,
  );

  const send_transaction_result = useSelector(
    (state: RootState) =>
      state.wallet_state.wallets[id].send_transaction_result,
  );
  const syncing = useSelector(
    (state: RootState) => state.wallet_state.status.syncing,
  );

  const result = get_transaction_result(send_transaction_result);
  const result_message = result.message;
  const result_class = result.success
    ? classes.resultSuccess
    : classes.resultFailure;

  function farm() {
    const address = address_input.value;
    if (address !== '') {
      dispatch(farm_block(address));
    }
  }

  function send() {
    if (sending_transaction) {
      return;
    }
    if (syncing) {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>Please finish syncing before making a transaction</Trans>
          </AlertDialog>,
        ),
      );
      return;
    }

    let address = address_input.value.trim();
    if (
      amount_input.value === '' ||
      Number(amount_input.value) === 0 ||
      !Number(amount_input.value) ||
      Number.isNaN(Number(amount_input.value))
    ) {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>Please enter a valid numeric amount</Trans>
          </AlertDialog>,
        ),
      );
      return;
    }
    if (fee_input.value === '' || Number.isNaN(Number(fee_input.value))) {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>Please enter a valid numeric fee</Trans>
          </AlertDialog>,
        ),
      );
      return;
    }
    const amount = chia_to_mojo(amount_input.value);
    const fee = chia_to_mojo(fee_input.value);

    if (address.includes('colour')) {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>
              Error: Cannot send chia to coloured address. Please enter a chia
              address.
            </Trans>
          </AlertDialog>,
        ),
      );
      return;
    }
    if (address.slice(0, 12) === 'chia_addr://') {
      address = address.slice(12);
    }
    if (address.startsWith('0x') || address.startsWith('0X')) {
      address = address.slice(2);
    }

    const amount_value = Number.parseFloat(amount);
    const fee_value = Number.parseFloat(fee);

    dispatch(send_transaction(id, amount_value, fee_value, address));
    address_input.value = '';
    amount_input.value = '';
    fee_input.value = '';
  }

  return (
    <Card title={<Trans>Create Transaction</Trans>}>
      {result_message && (
        <Grid item xs={12}>
          <p className={result_class}>{result_message}</p>
        </Grid>
      )}
      <Grid item xs={12}>
        <Box display="flex">
          <Box flexGrow={1}>
            <TextField
              id="filled-secondary"
              variant="filled"
              color="secondary"
              fullWidth
              disabled={sending_transaction}
              inputRef={(input) => {
                address_input = input;
              }}
              label={<Trans>Address / Puzzle hash</Trans>}
            />
          </Box>
          <Box />
        </Box>
      </Grid>
      <Grid item xs={12}>
        <Box display="flex">
          <Box flexGrow={6}>
            <TextField
              id="filled-secondary"
              variant="filled"
              color="secondary"
              fullWidth
              disabled={sending_transaction}
              className={classes.amountField}
              margin="normal"
              inputRef={(input) => {
                amount_input = input;
              }}
              label={<Trans>Amount</Trans>}
            />
          </Box>
          <Box flexGrow={6}>
            <TextField
              id="filled-secondary"
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
          <Box flexGrow={1}>
            <Button
              onClick={farm}
              className={classes.sendButton}
              style={config.local_test ? {} : { visibility: 'hidden' }}
              variant="contained"
              color="primary"
            >
              <Trans>Farm</Trans>
            </Button>
          </Box>
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
}

type AddressCardProps = {
  wallet_id: number;
};

function AddressCard(props: AddressCardProps) {
  const id = props.wallet_id;
  const address = useSelector(
    (state: RootState) => state.wallet_state.wallets[id].address,
  );
  const classes = useStyles();
  const dispatch = useDispatch();

  function newAddress() {
    dispatch(get_address(id, true));
  }

  function copy() {
    navigator.clipboard.writeText(address);
  }

  return (
    <Card 
      title={<Trans>Receive Address</Trans>}
      tooltip={(
        <Trans>
          HD or Hierarchical Deterministic keys are a type of public key/private key scheme where one private key can have a nearly infinite number of different public keys (and therefor wallet receive addresses) that will all ultimately come back to and be spendable by a single private key.
        </Trans>
      )}
    >
      <Grid item xs={12}>
        <Box display="flex">
          <Box flexGrow={1}>
            <TextField
              disabled
              fullWidth
              label={<Trans>Address</Trans>}
              value={address}
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
        <Box display="flex">
          <Box flexGrow={1} />
          <Box>
            <Button
              onClick={newAddress}
              className={classes.sendButton}
              variant="contained"
              color="primary"
            >
              <Trans>New Address</Trans>
            </Button>
          </Box>
        </Box>
      </Grid>
    </Card>
  );
}

type StandardWalletProps = {
  wallet_id: number;
};

export default function StandardWallet(props: StandardWalletProps) {
  const id = props.wallet_id;
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);

  if (wallets.length > props.wallet_id) {
    return (
      <Flex flexDirection="column" gap={3}>
        <BalanceCard wallet_id={id} />
        <SendCard wallet_id={id} />
        <AddressCard wallet_id={id} />
        <WalletHistory walletId={id} />
      </Flex>
    );
  }

  return null;
}
