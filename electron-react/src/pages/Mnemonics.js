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
  paper: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
  },
  avatar: {
    marginTop: theme.spacing(8),
    backgroundColor: theme.palette.secondary.main,
  },
  form: {
    width: '100%', // Fix IE 11 issue.
    marginTop: theme.spacing(5),
  },
  textField: {
      borderColor: "#ffffff"
  },
  submit: {
    marginTop: theme.spacing(5),
    marginBottom: theme.spacing(3),
  }
}));

export default function Mnemonics() {
  const theme = useTheme();
  const classes = useStyles(theme);
  
  return (
    <div className={classes.root}>
    <Container component="main" maxWidth="xs" >
      <CssBaseline />
      <div className={classes.paper}>

        <Avatar className={classes.avatar}>
          <LockOutlinedIcon />
        </Avatar>
        <Typography component="h1" variant="h5">
          Sign in
        </Typography>
        <form className={classes.form} noValidate>
          <CssTextField
            variant="outlined"
            margin="normal"
            required
            fullWidth
            color="primary" 
            id="email"
            label="Email Address"
            name="email"
            autoComplete="email"
            autoFocus
          />
          <CssTextField
            variant="outlined"
            margin="normal"
            required
            fullWidth
            name="password"
            label="Password"
            type="password"
            id="password"
            autoComplete="current-password"
            InputProps={{
                className: classes.input
              }}
          />
          <Button
            type="submit"
            fullWidth
            variant="contained"
            color="primary"
            className={classes.submit}
          >
            Sign In
          </Button>
          <Grid container>
            <Grid item xs>

            </Grid>
            <Grid item>
              <Link href="#" variant="body2">
                {"Run Full Node without keys"}
              </Link>
            </Grid>
          </Grid>
        </form>
      </div>
    </Container>
    </div>
  );
}