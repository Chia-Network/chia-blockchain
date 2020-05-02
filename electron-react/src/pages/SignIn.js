import React from 'react';
import Avatar from '@material-ui/core/Avatar';
import Button from '@material-ui/core/Button';
import CssBaseline from '@material-ui/core/CssBaseline';
import TextField from '@material-ui/core/TextField';
import FormControlLabel from '@material-ui/core/FormControlLabel';
import Checkbox from '@material-ui/core/Checkbox';
import Link from '@material-ui/core/Link';
import Grid from '@material-ui/core/Grid';
import Box from '@material-ui/core/Box';
import LockOutlinedIcon from '@material-ui/icons/LockOutlined';
import Typography from '@material-ui/core/Typography';
import { withStyles, makeStyles } from '@material-ui/core/styles';
import Container from '@material-ui/core/Container';
import { useTheme } from '@material-ui/core/styles';
import logo from '../assets/img/chia_logo.svg'; // Tell webpack this JS file uses this image


function Copyright() {
  return (
    <Typography variant="body2" color="textSecondary" align="center">
      {'Copyright © '}
      <Link color="inherit" href="https://chia.net">
        Your Website
      </Link>{' '}
      {new Date().getFullYear()}
      {'.'}
    </Typography>
  );
}
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
        }
      },
      "color": "#ffffff",
      "& .MuiOutlinedInput-input": {
          color: "#ffffff"
      }
    }
  })(TextField);

const useStyles = makeStyles((theme) => ({
  root: {
    background: 'linear-gradient(45deg, #142229 30%, #112240 90%)',
    height:'100%',
    },
  paper: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    height: '100%',
  },
  form: {
    width: '100%', // Fix IE 11 issue.
    marginTop: theme.spacing(5),
  },
  textField: {
      borderColor: "#ffffff"
  },
  topButton: {
    height: 45,
    marginTop: theme.spacing(15),
    marginBottom: theme.spacing(1),
  },
  lowerButton: {
    height: 45,
    marginTop: theme.spacing(1),
    marginBottom: theme.spacing(3),
  },
  logo: {
    marginTop: theme.spacing(8),
    marginBottom: theme.spacing(3),
  },
  main: {
    height: '100%'
  }
}));

export default function SignIn() {
  const classes = useStyles();
  
  return (
    <div className={classes.root}>
    <Container className={classes.main} component="main" maxWidth="xs" >
      <CssBaseline />
      <div className={classes.paper}>
      <img className ={classes.logo} src={logo} alt="Logo" />;
      <div>
        <Link href="/Mnemonics">
            <Button
                type="submit"
                fullWidth
                variant="contained"
                color="primary"
                className={classes.topButton}
            >
                Enter Mnemonics
            </Button>
          </Link>
          <Link href="/CreateMnemonics">
            <Button
                type="submit"
                fullWidth
                variant="contained"
                color="primary"
                className={classes.lowerButton}
            >
                Generate New Keys
            </Button>
          </Link>
          </div>
          <Grid container>
            <Grid item xs>

            </Grid>
            <Grid item>
              <Link href="/Mnemonics" variant="body2">
                {"Run Full Node without keys"}
              </Link>
            </Grid>
          </Grid>
      </div>
    </Container>
    </div>
  );
}