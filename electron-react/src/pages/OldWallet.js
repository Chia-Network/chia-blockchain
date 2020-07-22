import React, { Component } from "react";
import Button from "@material-ui/core/Button";
import CssBaseline from "@material-ui/core/CssBaseline";
import Link from "@material-ui/core/Link";
import Grid from "@material-ui/core/Grid";
import { withTheme } from "@material-ui/styles";
import Container from "@material-ui/core/Container";
import ArrowBackIosIcon from "@material-ui/icons/ArrowBackIos";
import { connect, useSelector } from "react-redux";
import { withRouter } from "react-router-dom";
import CssTextField from "../components/cssTextField";
import { useStore, useDispatch } from "react-redux";
import { mnemonic_word_added, resetMnemonic } from "../modules/mnemonic_input";
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
        autoComplete="off"
        variant="outlined"
        margin="normal"
        fullWidth
        color="primary"
        id={props.id}
        label={props.index}
        error={props.error}
        autoFocus={props.autofocus}
        defaultValue=""
        onChange={props.onChange}
      />
    </Grid>
  );
};

const Iterator = props => {
  const dispatch = useDispatch();
  const mnemonic_state = useSelector(state => state.mnemonic_state);
  const incorrect_word = useSelector(
    state => state.mnemonic_state.incorrect_word
  );

  function handleTextFieldChange(e) {
    var id = e.target.id + "";
    var clean_id = id.replace("id_", "");
    var int_val = parseInt(clean_id) - 1;
    var data = { word: e.target.value, id: int_val };
    dispatch(mnemonic_word_added(data));
  }
  var indents = [];
  for (var i = 0; i < 24; i++) {
    var focus = i === 0;
    indents.push(
      <MnemonicField
        onChange={handleTextFieldChange}
        key={i}
        error={
          (props.submitted && mnemonic_state.mnemonic_input[i] === "") ||
          mnemonic_state.mnemonic_input[i] === incorrect_word
        }
        autofocus={focus}
        id={"id_" + (i + 1)}
        index={i + 1}
      />
    );
  }
  return indents;
};

const UIPart = () => {
  function goBack() {
    dispatch(resetMnemonic());
    dispatch(changeEntranceMenu(presentSelectKeys));
  }
  const store = useStore();
  const dispatch = useDispatch();
  const [submitted, setSubmitted] = React.useState(false);
  const classes = useStyles();

  function enterMnemonic() {
    setSubmitted(true);
    var state = store.getState();
    var mnemonic = state.mnemonic_state.mnemonic_input;
    for (var i = 0; i < mnemonic.length; i++) {
      if (mnemonic[i] === "") {
        return;
      }
    }
    dispatch(add_key(mnemonic));
  }

  return (
    <div className={classes.root}>
      <Link onClick={goBack} href="#">
        <ArrowBackIosIcon className={classes.navigator}> </ArrowBackIosIcon>
      </Link>
      <div className={classes.grid_wrap}>
        <img className={classes.logo} src={logo} alt="Logo" />
        <Container className={classes.grid} maxWidth="lg">
          <h1 className={classes.title}>Import Wallet from Mnemonics</h1>
          <p className={classes.whiteP}>
            Enter the 24 word mmemonic that you have saved in order to restore
            your Chia wallet.
          </p>
          <Grid container spacing={2}>
            <Iterator submitted={submitted}></Iterator>
          </Grid>
        </Container>
      </div>
      <Container component="main" maxWidth="xs">
        <CssBaseline />
        <div className={classes.paper}>
          <Button
            onClick={enterMnemonic}
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

class OldWallet extends Component {
  constructor(props) {
    super(props);
    this.words = [];
    this.classes = props.theme;
  }

  componentDidMount(props) {
    console.log("Input Mnemonic");
  }

  render() {
    return <UIPart props={this.props}></UIPart>;
  }
}

export default withTheme(withRouter(connect()(OldWallet)));
