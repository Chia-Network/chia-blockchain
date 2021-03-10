import React, { ReactNode } from 'react';
import Grid from '@material-ui/core/Grid';
import { makeStyles } from '@material-ui/core/styles';
import { useDispatch, useSelector } from 'react-redux';
import { Trans } from '@lingui/macro';
import { AlertDialog, Card, Flex } from '@chia/core';
import Typography from '@material-ui/core/Typography';
import ExpandMoreIcon from '@material-ui/icons/ExpandMore';
import {
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Box,
  Button,
  TextField,
} from '@material-ui/core';
import {
  get_address,
  cc_spend,
  farm_block,
  rename_cc_wallet,
} from '../../../modules/message';
import {
  mojo_to_colouredcoin_string,
  colouredcoin_to_mojo,
} from '../../../util/chia';
import { openDialog } from '../../../modules/dialog';
import { get_transaction_result } from '../../../util/transaction_result';
import config from '../../../config/config';
import type { RootState } from '../../../modules/rootReducer';
import WalletHistory from '../WalletHistory';
import useCurrencyCode from '../../../hooks/useCurrencyCode';

const drawerWidth = 240;

const useStyles = makeStyles((theme) => ({
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
    padding: theme.spacing(1),
    margin: theme.spacing(1),
    marginBottom: theme.spacing(2),
    marginTop: theme.spacing(2),
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
  colourCard: {
    overflowWrap: 'break-word',
    marginTop: theme.spacing(2),
    paddingBottom: 20,
  },
  amountField: {
    paddingRight: 20,
  },
}));

type ColourCardProps = {
  wallet_id: number;
};

function ColourCard(props: ColourCardProps) {
  const id = props.wallet_id;

  const dispatch = useDispatch();
  const colour = useSelector(
    (state: RootState) => state.wallet_state.wallets[id].colour,
  );
  const name = useSelector(
    (state: RootState) => state.wallet_state.wallets[id].name,
  );

  let name_input: HTMLInputElement;

  function rename() {
    dispatch(rename_cc_wallet(id, name_input.value));
  }

  const classes = useStyles();
  return (
    <Card
      title={<Trans>Colour Info</Trans>}
    >
      <Grid item xs={12}>
        <Box display="flex">
          <Box>
            <Typography>
              <Trans>Colour:</Trans>
            </Typography>
          </Box>
          <Box
            style={{
              wordBreak: 'break-word',
              minWidth: '0',
            }}
          >
            <Typography variant="subtitle1">{colour}</Typography>
          </Box>
        </Box>
      </Grid>
      <Grid item xs={12}>
        <Box display="flex">
          <Box flexGrow={1}>
            <TextField
              id="filled-secondary"
              variant="filled"
              color="secondary"
              fullWidth
              label={<Trans>Nickname</Trans>}
              inputRef={(input) => {
                name_input = input;
              }}
              defaultValue={name}
              key={name}
            />
          </Box>
          <Box>
            <Button
              onClick={rename}
              className={classes.copyButton}
              variant="contained"
              color="secondary"
              disableElevation
            >
              <Trans>Rename</Trans>
            </Button>
          </Box>
        </Box>
      </Grid>
    </Card>
  );
}

type BalanceCardSubSectionProps = {
  title: ReactNode;
  balance: number;
  name: string;
};

function BalanceCardSubSection(props: BalanceCardSubSectionProps) {
  let cc_unit = props.name;
  if (cc_unit.length > 10) {
    cc_unit = `${cc_unit.slice(0, 10)}...`;
  }
  return (
    <Grid item xs={12}>
      <Box display="flex">
        <Box flexGrow={1}>
          <Typography variant="subtitle1">{props.title}</Typography>
        </Box>
        <Box>
          <Typography variant="subtitle1">
            {mojo_to_colouredcoin_string(props.balance)} {cc_unit}
          </Typography>
        </Box>
      </Box>
    </Grid>
  );
}

function get_cc_unit(name: string): string {
  let cc_unit = name;
  if (cc_unit.length > 10) {
    cc_unit = `${cc_unit.slice(0, 10)}...`;
  }
  return cc_unit;
}

type BalanceCardProps = {
  wallet_id: number;
};

function BalanceCard(props: BalanceCardProps) {
  const id = props.wallet_id;
  let name = useSelector(
    (state: RootState) => state.wallet_state.wallets[id].name,
  );
  if (!name) {
    name = '';
  }
  const cc_unit = get_cc_unit(name);

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

  const balancebox_1 = "<table width='100%'>";
  const balancebox_2 = "<tr><td align='left'>";
  const balancebox_3 = "</td><td align='right'>";
  const balancebox_4 = '</td></tr>';
  const balancebox_row = "<tr height='8px'></tr>";
  const balancebox_5 = '</td></tr></table>';
  const balancebox_ptotal = 'Pending Total Balance';
  const balancebox_pending = 'Pending Transactions';
  const balancebox_change = 'Pending Change';
  const balancebox_unit = ` ${cc_unit}`;
  const balancebox_hline =
    "<tr><td colspan='2' style='text-align:center'><hr width='50%'></td></tr>";
  const balance_ptotal_chia = mojo_to_colouredcoin_string(balance_ptotal);
  const balance_pending_chia = mojo_to_colouredcoin_string(balance_pending);
  const balance_change_chia = mojo_to_colouredcoin_string(balance_change);
  const acc_content =
    balancebox_1 +
    balancebox_2 +
    balancebox_ptotal +
    balancebox_3 +
    balance_ptotal_chia +
    balancebox_unit +
    balancebox_hline +
    balancebox_4 +
    balancebox_row +
    balancebox_2 +
    balancebox_pending +
    balancebox_3 +
    balance_pending_chia +
    balancebox_unit +
    balancebox_4 +
    balancebox_row +
    balancebox_2 +
    balancebox_change +
    balancebox_3 +
    balance_change_chia +
    balancebox_unit +
    balancebox_5;

  return (
    <Card
      title={<Trans>Balance</Trans>}
    >
      <BalanceCardSubSection
        title={
          <Trans>Total Balance</Trans>
        }
        balance={balance}
        name={name}
      />
      <BalanceCardSubSection
        title={
          <Trans>
            Spendable Balance
          </Trans>
        }
        balance={balance_spendable}
        name={name}
      />
      <Grid item xs={12}>
        <Box display="flex">
          <Box flexGrow={1}>
            <Accordion>
              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                <Trans>
                  View pending balances...
                </Trans>
              </AccordionSummary>
              <AccordionDetails>
                <div dangerouslySetInnerHTML={{ __html: acc_content }} />
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
  let name = useSelector(
    (state: RootState) => state.wallet_state.wallets[id].name,
  );
  if (!name) {
    name = '';
  }
  const cc_unit = get_cc_unit(name);
  const currencyCode = useCurrencyCode();

  const sending_transaction = useSelector(
    (state: RootState) => state.wallet_state.wallets[id].sending_transaction,
  );

  const send_transaction_result = useSelector(
    (state: RootState) =>
      state.wallet_state.wallets[id].send_transaction_result,
  );

  const colour = useSelector(
    (state: RootState) => state.wallet_state.wallets[id].colour,
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
      dispatch(openDialog(
        <AlertDialog>
          Please finish syncing before making a transaction
        </AlertDialog>
      ));
      return;
    }
    let address = address_input.value.trim();
    if (
      amount_input.value === '' ||
      Number(amount_input.value) === 0 ||
      !Number(amount_input.value) ||
      Number.isNaN(Number(amount_input.value))
    ) {
      dispatch(openDialog(
        <AlertDialog>
          Please enter a valid numeric amount
        </AlertDialog>
      ));
      return;
    }
    if (fee_input.value === '' || Number.isNaN(Number(fee_input.value))) {
      dispatch(openDialog(
        <AlertDialog>
          Please enter a valid numeric fee
        </AlertDialog>
      ));
      return;
    }

    const amount = colouredcoin_to_mojo(amount_input.value);
    const fee = colouredcoin_to_mojo(fee_input.value);

    if (address.includes('chia_addr') || address.includes('colour_desc')) {
      dispatch(
        openDialog(
          <AlertDialog>
            Error: recipient address is not a coloured wallet address. Please enter a coloured wallet address
          </AlertDialog>
        ),
      );
      return;
    }
    if (address.slice(0, 14) === 'colour_addr://') {
      const colour_id = address.slice(14, 78);
      address = address.slice(79);
      if (colour_id !== colour) {
        dispatch(
          openDialog(
            <AlertDialog>
              Error the entered address appears to be for a different colour.
            </AlertDialog>
          ),
        );
        return;
      }
    }

    if (address.startsWith('0x') || address.startsWith('0X')) {
      address = address.slice(2);
    }

    const amount_value = Number.parseFloat(amount);
    const fee_value = Number.parseFloat(fee);

    if (fee_value !== 0) {
      dispatch(
        openDialog(
          <AlertDialog>
            Please enter 0 fee. Positive fees not supported yet for coloured coins.
          </AlertDialog>
        ),
      );
      return;
    }

    dispatch(cc_spend(id, address, amount_value, fee_value));
    address_input.value = '';
    amount_input.value = '';
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
              id="filled-secondary"
              variant="filled"
              color="secondary"
              fullWidth
              disabled={sending_transaction}
              inputRef={(input) => {
                address_input = input;
              }}
              label={<Trans>Address</Trans>}
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
              margin="normal"
              className={classes.amountField}
              inputRef={(input) => {
                amount_input = input;
              }}
              label={
                <Trans>
                  Amount ({cc_unit})
                </Trans>
              }
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
              label={<Trans>Fee ({currencyCode})</Trans>}
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
              variant="contained"
              color="primary"
              style={config.local_test ? {} : { visibility: 'hidden' }}
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
    dispatch(get_address(id));
  }

  function copy() {
    navigator.clipboard.writeText(address);
  }

  return (
    <Card
      title={<Trans>Receive Address</Trans>}
    >
      <Grid item xs={12}>
        <Box display="flex">
          <Box flexGrow={1}>
            <TextField
              disabled
              fullWidth
              label={
                <Trans>Address</Trans>
              }
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

type ColouredWalletProps = {
  wallet_id: number;
};

export default function ColouredWallet(props: ColouredWalletProps) {
  const id = useSelector((state: RootState) => state.wallet_menu.id);
  const wallets = useSelector((state: RootState) => state.wallet_state.wallets);

  if (wallets.length > props.wallet_id) {
    return (
      <Flex flexDirection="column" gap={3}>
        <ColourCard wallet_id={id} />
        <BalanceCard wallet_id={id} />
        <SendCard wallet_id={id} />
        <AddressCard wallet_id={id} />
        <WalletHistory walletId={id} />
      </Flex>
    );
  }

  return null;
}
