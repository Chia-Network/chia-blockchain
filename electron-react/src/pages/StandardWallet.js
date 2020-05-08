import React from 'react';
import CssBaseline from '@material-ui/core/CssBaseline';
import Grid from '@material-ui/core/Grid';
import { makeStyles } from '@material-ui/core/styles';
import Container from '@material-ui/core/Container';
import { withRouter, Redirect } from 'react-router-dom'
import { connect, useDispatch, useSelector } from 'react-redux';
import { log_out } from '../modules/message';
import clsx from 'clsx';
import Drawer from '@material-ui/core/Drawer';
import List from '@material-ui/core/List';
import Typography from '@material-ui/core/Typography';
import Divider from '@material-ui/core/Divider';
import ListItem from '@material-ui/core/ListItem';
import ListItemIcon from '@material-ui/core/ListItemIcon';
import ListItemText from '@material-ui/core/ListItemText';
import ListSubheader from '@material-ui/core/ListSubheader';
import DashboardIcon from '@material-ui/icons/Dashboard';
import Paper from '@material-ui/core/Paper';
import Box from '@material-ui/core/Box';
import TextField from '@material-ui/core/TextField';
import Button from '@material-ui/core/Button';
import Table from '@material-ui/core/Table';
import TableBody from '@material-ui/core/TableBody';
import TableCell from '@material-ui/core/TableCell';
import TableContainer from '@material-ui/core/TableContainer';
import TableHead from '@material-ui/core/TableHead';
import TableRow from '@material-ui/core/TableRow';
import { get_puzzle_hash } from '../modules/message';

const drawerWidth = 240;

const useStyles = makeStyles((theme) => ({
    root: {
        display: 'flex',
        paddingLeft: '0px'
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
        padding: theme.spacing(0),
        display: 'flex',
        overflow: 'auto',
        flexDirection: 'column',
    },
    fixedHeight: {
        height: 240,
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
        height: 200,
        marginTop: theme.spacing(2),
    },
    sendCard: {
        marginTop: theme.spacing(2),
    },
    sendButton: {
        marginTop: theme.spacing(2),
        marginBottom: theme.spacing(2),
        width: 150,
        height: 50
    },
    copyButton: {
        marginTop: theme.spacing(0),
        marginBottom: theme.spacing(0),
        width: 50,
        height: 56
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
        marginBottom: theme.spacing(5)
    }, 
    table: {
        minWidth: 650,
        maxHeight: 400,
    },
}));

const BalanceCard = (props) => {
    var id = props.wallet_id
    const balance = useSelector(state => state.wallet_state.wallets[id].balance_total)
    const balance_pending = useSelector(state => state.wallet_state.wallets[id].balance_pending)

    const classes = useStyles();
    return (
        <Paper className={classes.paper, classes.balancePaper}>
            <Grid container spacing={0}>
                <Grid item xs={12}>
                    <div className={classes.cardTitle} >
                        <Typography component="h6" variant="h6">
                            Balance
                        </Typography>
                    </div>
                </Grid>
                <Grid item xs={12}>
                    <div className={classes.cardSubSection} >
                        <Box display="flex">
                            <Box flexGrow={1} >
                                <Typography component="subtitle1" variant="subtitle1">
                                    Total Balance
                                </Typography>
                            </Box>
                            <Box>
                                <Typography alignRight component="subtitle1" variant="subtitle1">
                                    {balance} XCH
                                </Typography>
                            </Box>
                        </Box>
                    </div>
                </Grid>
                <Grid item xs={12}>
                    <div className={classes.cardSubSection} >
                        <Box display="flex">
                            <Box flexGrow={1} >
                                <Typography component="subtitle1" variant="subtitle1">
                                    Pending Balance
                                </Typography>
                            </Box>
                            <Box>
                                <Typography alignRight component="subtitle1" variant="subtitle1">
                                    {balance_pending} XCH
                                </Typography>
                            </Box>
                        </Box>
                    </div>
                </Grid>
            </Grid>
        </Paper>
    )
}

const SendCard = (props) => {
    var id = props.wallet_id
    const classes = useStyles();
    return (
        <Paper className={classes.paper, classes.sendCard}>
            <Grid container spacing={0}>
                <Grid item xs={12}>
                    <div className={classes.cardTitle} >
                        <Typography component="h6" variant="h6">
                            Create Transaction
                        </Typography>
                    </div>
                </Grid>
                <Grid item xs={12}>
                    <div className={classes.cardSubSection} >
                        <Box display="flex">
                            <Box flexGrow={1} >
                                <TextField fullWidth id="outlined-basic" label="Address" variant="outlined" />
                            </Box>
                            <Box>

                            </Box>
                        </Box>
                    </div>
                </Grid>
                <Grid item xs={12}>
                    <div className={classes.cardSubSection} >
                        <Box display="flex">
                            <Box flexGrow={1} >
                                <TextField fullWidth id="outlined-basic" label="Amount" variant="outlined" />
                            </Box>
                        </Box>
                    </div>
                </Grid>
                <Grid item xs={12}>
                    <div className={classes.cardSubSection} >
                        <Box display="flex">
                            <Box flexGrow={1} >
                            </Box>
                            <Box>
                                <Button className={classes.sendButton} variant="contained" color="primary">
                                    Send
                                </Button>
                            </Box>
                        </Box>

                    </div>
                </Grid>
            </Grid>
        </Paper>
    )
}

const HistoryCard = (props) => {
    var id = props.wallet_id
    const classes = useStyles();
    return (
        <Paper className={classes.paper, classes.sendCard}>
            <Grid container spacing={0}>
                <Grid item xs={12}>
                    <div className={classes.cardTitle} >
                        <Typography component="h6" variant="h6">
                            Transaction History
                        </Typography>
                    </div>
                </Grid>
                <Grid item xs={12}>
                    <TransactionTable wallet_id={id}></TransactionTable>
                </Grid>
            </Grid>
        </Paper>
    )
}

const TransactionTable = (props) => {
    const classes = useStyles();
    var id = props.wallet_id
    const transactions = useSelector(state => state.wallet_state.wallets[id].transactions)
    return (
        <TableContainer className={classes.table}  component={Paper}>
        <Table stickyHeader className={classes.table} aria-label="simple table">
          <TableHead>
            <TableRow>
              <TableCell >Type</TableCell>
              <TableCell >To</TableCell>
              <TableCell >Date</TableCell>
              <TableCell >Status</TableCell>
              <TableCell >Amount</TableCell>
              <TableCell >Fee</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {transactions.map((tx) => (
              <TableRow key={tx}>
                <TableCell component="th" scope="row">
                  {tx}
                </TableCell>
                <TableCell >{tx}</TableCell>
                <TableCell >{tx}</TableCell>
                <TableCell >{tx}</TableCell>
                <TableCell >{tx}</TableCell>
                <TableCell >{tx}</TableCell>

              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    )
}

const AddressCard = (props) => {
    var id = props.wallet_id
    const puzzle_hash = useSelector(state => state.wallet_state.wallets[id].puzzle_hash)
    const classes = useStyles();
    const dispatch = useDispatch()

    function newAddress() {
        console.log("Dispatch for id: " + id)
        dispatch(get_puzzle_hash(id))
    }

    function copy() {
        navigator.clipboard.writeText(puzzle_hash)
    }
 
    return (
        <Paper className={classes.paper, classes.sendCard}>
            <Grid container spacing={0}>
                <Grid item xs={12}>
                    <div className={classes.cardTitle} >
                        <Typography component="h6" variant="h6">
                            Receive Addresss
                        </Typography>
                    </div>
                </Grid>
                <Grid item xs={12}>
                    <div className={classes.cardSubSection} >
                        <Box display="flex">
                            <Box flexGrow={1} >
                                <TextField disabled fullWidth id="outlined-basic" label="Address" value={puzzle_hash} variant="outlined" />
                            </Box>
                            <Box>
                                <Button onClick={copy} className={classes.copyButton} variant="contained" color="secondary" disableElevation>
                                    Copy
                                </Button>
                            </Box>
                        </Box>
                    </div>
                </Grid>
                <Grid item xs={12}>
                    <div className={classes.cardSubSection} >
                        <Box display="flex">
                            <Box flexGrow={1} >
                            </Box>
                            <Box>
                                <Button onClick={newAddress} className={classes.sendButton} variant="contained" color="primary">
                                    New Address
                                </Button>
                            </Box>
                        </Box>

                    </div>
                </Grid>
            </Grid>
        </Paper>
    )
}

const StandardWallet = (props) => {
    const classes = useStyles();
    var id = props.wallet_id

    return (
        <Grid className={classes.walletContainer} item xs={12}>
            <BalanceCard wallet_id={id}></BalanceCard>
            <SendCard wallet_id={id}></SendCard>
            <AddressCard wallet_id={id}> </AddressCard>
            <HistoryCard wallet_id={id}></HistoryCard>
        </Grid>
    );
}

export default withRouter(connect()(StandardWallet));
