import React, { Component } from "react";
import Button from "@material-ui/core/Button";
import CssBaseline from "@material-ui/core/CssBaseline";
import TextField from "@material-ui/core/TextField";
import Grid from "@material-ui/core/Grid";
import Typography from "@material-ui/core/Typography";
import { withTheme, withStyles, makeStyles } from "@material-ui/styles";
import Container from "@material-ui/core/Container";
import ArrowBackIosIcon from "@material-ui/icons/ArrowBackIos";
import { connect, useSelector, useDispatch } from "react-redux";
import { genereate_mnemonics } from "../modules/message";
import { withRouter } from "react-router-dom";

// function Copyright() {
//   return (
//     <Typography variant="body2" color="textSecondary" align="center">
//       {"Copyright © "}
//       <Link color="inherit" href="https://chia.net">
//         Your Website
//       </Link>{" "}
//       {new Date().getFullYear()}
//       {"."}
//     </Typography>
//   );
// }

const CssTextField = withStyles({
  root: {
    "& MuiFormLabel-root": {
      color: "#e3f2fd"
    },
    "& label.Mui-focused": {
      color: "#e3f2fd"
    },
    "& label.Mui-required": {
      color: "#e3f2fd"
    },
    "& label.Mui-disabled": {
      color: "#e3f2fd"
    },
    "& .MuiInput-underline:after": {
      borderBottomColor: "#e3f2fd"
    },
    "& .MuiOutlinedInput-root": {
      "& fieldset": {
        borderColor: "#e3f2fd"
      },
      "&:hover fieldset": {
        borderColor: "#e3f2fd"
      },
      "&.Mui-focused fieldset": {
        borderColor: "#e3f2fd"
      },
      "&.Mui-disabled fieldset": {
        borderColor: "#e3f2fd"
      }
    },
    color: "#ffffff",
    "& .MuiOutlinedInput-input": {
      color: "#ffffff"
    }
  }
})(TextField);

const useStyles = makeStyles(theme => ({
  root: {
    background: "linear-gradient(45deg, #142229 30%, #112240 90%)",
    height: "100%"
  },
  paper: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center"
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
  grid: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    paddingTop: theme.spacing(5)
  },
  grid_item: {
    paddingTop: 10,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    backgroundColor: "#444444",
    color: "#ffffff",
    height: 50,
    verticalAlign: "middle"
  },
  title: {
    color: "#ffffff",
    marginTop: theme.spacing(4),
    marginBottom: theme.spacing(8)
  },
  navigator: {
    color: "#ffffff",
    marginTop: theme.spacing(4),
    marginLeft: theme.spacing(4),
    fontSize: 35
  }
}));

class MnemonicLabel extends Component {
  render() {
    return (
      <Grid item xs={2}>
        <CssTextField
          variant="outlined"
          margin="normal"
          disabled
          fullWidth
          color="primary"
          id="email"
          label={this.props.index}
          name="email"
          autoComplete="email"
          autoFocus
          defaultValue={this.props.word}
        />
      </Grid>
    );
  }
}

const UIPart = () => {
  const words = useSelector(state => state.wallet_state.mnemonic);
  const classes = useStyles();
  return (
    <div className={classes.root}>
      <ArrowBackIosIcon className={classes.navigator}> </ArrowBackIosIcon>
      <Container className={classes.grid} maxWidth="lg">
        <Typography className={classes.title} component="h1" variant="h5">
          Write Down These Words
        </Typography>
        <Grid container spacing={3}>
          {words}
          {words.map((word, i) => (
            <MnemonicLabel word={word} index={i + 1} />
          ))}
        </Grid>
      </Container>
      <Container component="main" maxWidth="xs">
        <CssBaseline />
        <div className={classes.paper}>
          <Button
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

const CreateMnemonics = () => {
  var get_mnemonics = genereate_mnemonics();
  const dispatch = useDispatch();
  dispatch(get_mnemonics);

  return UIPart();
};

export default withTheme(withRouter(connect()(CreateMnemonics)));
