import React, { Component }  from 'react';
import Button from '@material-ui/core/Button';
import CssBaseline from '@material-ui/core/CssBaseline';
import Link from '@material-ui/core/Link';
import Grid from '@material-ui/core/Grid';
import Typography from '@material-ui/core/Typography';
import { withTheme } from '@material-ui/styles';
import Container from '@material-ui/core/Container';
import ArrowBackIosIcon from '@material-ui/icons/ArrowBackIos';
import { connect, useSelector } from 'react-redux';
import { withRouter } from 'react-router-dom'
import CssTextField from '../components/cssTextField'
import myStyle from './style'

const MnemonicField = (props) => {
    return (
      <Grid item xs={2}>
        <CssTextField
        variant="outlined"
        margin="normal"
        fullWidth
        color="primary" 
        id={props.id}
        label={props.index}
        name="email"
        autoComplete="email"
        autoFocus={props.autofocus}
        defaultValue=""
        />
      </Grid>
    )
}

const Iterator = (props) => {
    var indents = [];
    for (var i = 0; i < 24; i++) {
    var focus = i === 0
    indents.push(<MnemonicField key={i} autofocus ={focus} id={"id_"+(i+1)} index={i+1} />);
    }
    return indents;
}

const UIPart = (props) => {
    function goBack(){
        props.props.history.goBack();
    }

    const words = useSelector(state => state.wallet_state.mnemonic)
    const classes = myStyle();
    return(
      <div className={classes.root}>
      <Link onClick={goBack} href="#" variant="">
        <ArrowBackIosIcon className={classes.navigator}> </ArrowBackIosIcon>
      </Link>
      <div className={classes.grid_wrap}>
      <Container className={classes.grid} maxWidth="lg">
          <Typography className={classes.title} component="h1" variant="h5">
            Enter Your Mnemonics
          </Typography>
          <Grid container spacing={2}>
            <Iterator mnemonic={words}></Iterator>
          </Grid>
      </Container>
      </div>
      <Container component="main" maxWidth="xs" >
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
    )
  }


class OldWallet extends Component {
    constructor(props) {
        super(props);
        this.words = []
        this.classes = props.theme
      }
    
    
    componentDidMount(props) {
        console.log("Input Mnemonic")
    }
  
    render() {
        return(<UIPart props={this.props}></UIPart>)
    }
  }


export default withTheme(withRouter(connect()(OldWallet)));
