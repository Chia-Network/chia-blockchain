import React, { Component }  from 'react';
import Button from '@material-ui/core/Button';
import CssBaseline from '@material-ui/core/CssBaseline';
import Link from '@material-ui/core/Link';
import Grid from '@material-ui/core/Grid';
import Typography from '@material-ui/core/Typography';
import { withTheme } from '@material-ui/styles';
import Container from '@material-ui/core/Container';
import ArrowBackIosIcon from '@material-ui/icons/ArrowBackIos';
import { connect, useSelector, useDispatch } from 'react-redux';
import { genereate_mnemonics } from '../modules/message';
import { withRouter, Redirect} from 'react-router-dom'
import CssTextField from '../components/cssTextField'
import myStyle from './style'
import { log_in } from '../modules/message';

const MnemonicField = (props) => {
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
    )
}
const Iterator = (props) => {
    return  props.mnemonic.map((word, i) => <MnemonicField key={i} word={word} id={"id_"+(i+1)} index={i+1} />)
}

const UIPart = (props) => {
    const logged_in = useSelector(state => state.wallet_state.logged_in)
    const words = useSelector(state => state.wallet_state.mnemonic)
    const dispatch = useDispatch()
    const classes = myStyle();

    function goBack() {
      props.props.history.goBack();
    }

    function next() {
      dispatch(log_in(words))
    }

    if (logged_in) {
      return (<Redirect to="/dashboard" />)
    } 
    return(
      <div className={classes.root}>
      <Link onClick={goBack} href="#">
        <ArrowBackIosIcon className={classes.navigator}> </ArrowBackIosIcon>
      </Link>
      <div className={classes.grid_wrap}>
      <Container className={classes.grid} maxWidth="lg">
          <Typography className={classes.title} component="h1" variant="h5">
            Write Down These Words
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
    )
  }


class NewWallet extends Component {
    constructor(props) {
        super(props);
        this.words = []
        var get_mnemonics = genereate_mnemonics()
        props.dispatch(get_mnemonics)
        this.classes = props.theme
      }
    
    
    componentDidMount(props) {
        console.log("Get Mnemonic")
    }
  
    render() {
        return(<UIPart props={this.props}></UIPart>)
    }
  }

export default withTheme(withRouter(connect()(NewWallet)));
