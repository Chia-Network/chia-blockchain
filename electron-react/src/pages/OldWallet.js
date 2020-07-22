import React, { Component, useEffect } from "react";
import Button from "@material-ui/core/Button";
import CssBaseline from "@material-ui/core/CssBaseline";
import Link from "@material-ui/core/Link";
import Grid from "@material-ui/core/Grid";
import Typography from "@material-ui/core/Typography";
import { withTheme } from "@material-ui/styles";
import Container from "@material-ui/core/Container";
import ArrowBackIosIcon from "@material-ui/icons/ArrowBackIos";
import { connect, useSelector } from "react-redux";
import { withRouter } from "react-router-dom";
import CssTextField from "../components/cssTextField";
import myStyle from "./style";
import { useStore, useDispatch } from "react-redux";
import { mnemonic_word_added, resetMnemonic } from "../modules/mnemonic_input";
import { unselectFingerprint } from "../modules/message";
import {
  changeEntranceMenu,
  presentSelectKeys,
  presentRestoreBackup
} from "../modules/entranceMenu";
import { openDialog } from "../modules/dialogReducer";

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
  const store = useStore();
  var mnemonic = store.getState().state.mnemonic_state.mnemonic_input;

  function handleTextFieldChange(e) {
    console.log(e.target);
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
          (props.submitted && mnemonic[i] === "") ||
          mnemonic[i] == incorrect_word
        }
        autofocus={focus}
        id={"id_" + (i + 1)}
        index={i + 1}
      />
    );
  }
  return indents;
};

const UIPart = props => {
  function goBack() {
    dispatch(resetMnemonic());
    dispatch(changeEntranceMenu(presentSelectKeys));
  }
  const dispatch = useDispatch();
  const [submitted, setSubmitted] = React.useState(false);
  const incorrect_word = state.mnemonic_state.incorrect_word;

  function enterMnemonic() {
    dispatch(unselectFingerprint());
    dispatch(changeEntranceMenu(presentRestoreBackup));
    // setSubmitted(true);
    // var state = store.getState();
    // var mnemonic = state.mnemonic_state.mnemonic_input;
    // for (var i = 0; i < mnemonic.length; i++) {
    //   if (mnemonic[i] === "") {
    //     return;
    //   }
    // }
    // dispatch(add_key(mnemonic));
  }

  useEffect(() => {
    dispatch(
      openDialog(
        "Welcome!",
        `Enter the 24 word mmemonic that you have saved in order to restore your Chia wallet. `
      )
    );
  }, [dispatch]);

  const words = useSelector(state => state.mnemonic_state.mnemonic_input);
  const classes = myStyle();

  return (
    <div className={classes.root}>
      <Link onClick={goBack} href="#">
        <ArrowBackIosIcon className={classes.navigator}> </ArrowBackIosIcon>
      </Link>
      <div className={classes.grid_wrap}>
        <Container className={classes.grid} maxWidth="lg">
          <Typography className={classes.title} component="h4" variant="h4">
            Import Wallet from Mnemonics
          </Typography>
          <Grid container spacing={2}>
            <Iterator
              submitted={submitted}
              incorrect_word={incorrect_word}
            ></Iterator>
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
