import React, { Component } from "react";
import Button from "@material-ui/core/Button";
import CssBaseline from "@material-ui/core/CssBaseline";
import Grid from "@material-ui/core/Grid";
import { withTheme } from "@material-ui/styles";
import Container from "@material-ui/core/Container";
import ArrowBackIosIcon from "@material-ui/icons/ArrowBackIos";
import { connect, useSelector, useDispatch } from "react-redux";
import { genereate_mnemonics, add_new_key_action } from "../modules/message";
import { withRouter } from "react-router-dom";
import CssTextField from "../components/cssTextField";
import myStyle from "./style";
import { add_key } from "../modules/message";
import { changeEntranceMenu, presentSelectKeys } from "../modules/entranceMenu";
import { makeStyles } from "@material-ui/core/styles";
import logo from "../assets/img/chia_logo.svg";

const useStyles = makeStyles(theme => ({
  root: {
    background: "linear-gradient(45deg, #181818 30%, #333333 90%)",
    height: "100%"
  },
  paper: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    padding: theme.spacing(0)
  },
  avatar: {
    marginTop: theme.spacing(8),
    backgroundColor: theme.palette.secondary.main
  },
  form: {
    width: "100%", // Fix IE 11 issue.
    marginTop: theme.spacing(5)
  },
  textField: {
    borderColor: "#ffffff"
  },
  submit: {
    marginTop: theme.spacing(8),
    marginBottom: theme.spacing(3)
  },
  grid_wrap: {
    paddingLeft: theme.spacing(10),
    paddingRight: theme.spacing(10),
    textAlign: "center"
  },
  grid: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center"
  },
  grid_item: {
    padding: theme.spacing(1),
    paddingTop: 0,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    backgroundColor: "#444444",
    color: "#ffffff",
    height: 60
  },
  title: {
    color: "#ffffff",
    marginTop: theme.spacing(4),
    marginBottom: theme.spacing(2)
  },
  navigator: {
    color: "#ffffff",
    marginTop: theme.spacing(4),
    marginLeft: theme.spacing(4),
    fontSize: 35,
    flex: 1,
    align: "right"
  },
  instructions: {
    color: "#ffffff",
    fontSize: 18
  },
  logo: {
    marginTop: theme.spacing(0),
    marginBottom: theme.spacing(1)
  },
  whiteP: {
    color: "white",
    fontSize: "18px"
  }
}));

const MnemonicField = props => {
  return (
    <Grid item xs={2}>
      <CssTextField
        variant="outlined"
        margin="normal"
        disabled
        fullWidth
        color="primary"
        id={props.id}
        label={props.index}
        name="email"
        autoComplete="email"
        autoFocus
        value={props.word}
        height="60"
      />
    </Grid>
  );
};
const Iterator = props => {
  return props.mnemonic.map((word, i) => (
    <MnemonicField key={i} word={word} id={"id_" + (i + 1)} index={i + 1} />
  ));
};

const UIPart = props => {
  var words = useSelector(state => state.wallet_state.mnemonic);
  const dispatch = useDispatch();
  const classes = useStyles();
  if (!words) {
    words = [];
  }

  function goBack() {
    dispatch(changeEntranceMenu(presentSelectKeys));
  }

  function next() {
    dispatch(add_new_key_action(words));
  }

  return (
    <div className={classes.root}>
      <ArrowBackIosIcon onClick={goBack} className={classes.navigator}>
        {" "}
      </ArrowBackIosIcon>
      <div className={classes.grid_wrap}>
        <img className={classes.logo} src={logo} alt="Logo" />
        <Container className={classes.grid} maxWidth="lg">
          <h1 className={classes.title}>New Wallet</h1>
          <p className={classes.whiteP}>
            Welcome! The following words are used for your wallet backup.
            Without them, you will lose access to your wallet, keep them safe!
            Write down each word along with the order number next to them.
            (Order is important)
          </p>
          <Grid container spacing={2}>
            <Iterator mnemonic={words}></Iterator>
          </Grid>
        </Container>
      </div>
      <Container component="main" maxWidth="xs">
        <CssBaseline />
        <div className={classes.paper}>
          <Button
            onClick={next}
            type="submit"
            fullWidth
            variant="contained"
            color="primary"
            className={classes.submit}
          >
            Next
          </Button>
        </div>
      </Container>
    </div>
  );
};

class NewWallet extends Component {
  constructor(props) {
    super(props);
    this.words = [];
    var get_mnemonics = genereate_mnemonics();
    props.dispatch(get_mnemonics);
    this.classes = props.theme;
  }

  componentDidMount(props) {}

  render() {
    return <UIPart props={this.props}></UIPart>;
  }
}

export default withTheme(withRouter(connect()(NewWallet)));
