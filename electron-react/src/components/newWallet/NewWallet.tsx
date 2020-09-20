import React from "react";
import { Typography, Button, Grid, Container } from "@material-ui/core";
import { ArrowBackIos as ArrowBackIosIcon } from "@material-ui/icons";
import { useSelector, useDispatch } from "react-redux";
import { useEffectOnce } from 'react-use';
import { genereate_mnemonics, add_new_key_action } from "../../modules/message";
import TextField from "../form/TextField";
import type { RootState } from "../../modules/rootReducer";
import Logo from '../logo/Logo';
import Flex from '../flex/Flex';
import Loading from '../loading/Loading';
import Link from '../router/Link';
import LayoutHero from "../layout/LayoutHero";

const MnemonicField = (props: any) => {
  return (
    <Grid item xs={2}>
      <TextField
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
      />
    </Grid>
  );
};

export default function NewWallet() {
  const dispatch = useDispatch();
  const words = useSelector((state: RootState) => state.wallet_state.mnemonic);

  useEffectOnce(() => {
    const get_mnemonics = genereate_mnemonics();
    dispatch(get_mnemonics);
  });

  function handleNext() {
    dispatch(add_new_key_action(words));
  }

  return (
    <LayoutHero>
      <Container maxWidth="xl">
        <Link to="/">
          <ArrowBackIosIcon fontSize="large" color="secondary" />
        </Link>
      </Container>
      <Container maxWidth="lg">
        <Flex flexDirection="column" gap={3} alignItems="center">
          <Logo />
          <Typography variant="h4" component="h1" gutterBottom>
            New Wallet
          </Typography>
          <Typography variant="subtitle1" align="center">
            Welcome! The following words are used for your wallet backup.
            Without them, you will lose access to your wallet, keep them safe!
            Write down each word along with the order number next to them.
            (Order is important)
          </Typography>
          {!!words.length ? (
            <Grid container spacing={2}>
              {words.map((word, i) => (
                <MnemonicField key={i} word={word} id={"id_" + (i + 1)} index={i + 1} />
              ))}
            </Grid>
          ) : (
            <Loading />
          )}
          <Container maxWidth="xs">
            <Button
              onClick={handleNext}
              type="submit"
              variant="contained"
              color="primary"
              fullWidth
            >
              Next
            </Button>
          </Container>
        </Flex>
      </Container>
    </LayoutHero>
  );
}
