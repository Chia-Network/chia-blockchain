import React from 'react';
import { Trans } from '@lingui/macro';
import {
  TextField,
  Typography,
  Button,
  Grid,
  Container,
} from '@material-ui/core';
import { ArrowBackIos as ArrowBackIosIcon } from '@material-ui/icons';
import { useSelector, useDispatch } from 'react-redux';
import { useEffectOnce } from 'react-use';
import { Flex, Loading, Link, Logo } from '@chia/core';
import { genereate_mnemonics, add_new_key_action } from '../../modules/message';
import LayoutHero from '../layout/LayoutHero';
import type { RootState } from '../../modules/rootReducer';

const MnemonicField = (props: any) => (
  <Grid item xs={2}>
    <TextField
      variant="outlined"
      margin="normal"
      color="primary"
      id={props.id}
      label={props.index}
      name="email"
      autoComplete="email"
      value={props.word}
      inputProps={{
        readOnly: true,
      }}
      fullWidth
      autoFocus
    />
  </Grid>
);

export default function WalletAdd() {
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
    <LayoutHero
      header={
        <Link to="/">
          <ArrowBackIosIcon fontSize="large" color="secondary" />
        </Link>
      }
    >
      <Container maxWidth="lg">
        <Flex flexDirection="column" gap={3} alignItems="center">
          <Logo />
          <Typography variant="h4" component="h1" gutterBottom>
            <Trans>New Wallet</Trans>
          </Typography>
          <Typography variant="subtitle1" align="center">
            <Trans>
              Welcome! The following words are used for your wallet backup.
              Without them, you will lose access to your wallet, keep them safe!
              Write down each word along with the order number next to them.
              (Order is important)
            </Trans>
          </Typography>
          {words.length ? (
            <Grid container spacing={2}>
              {words.map((word: string, index: number) => (
                <MnemonicField
                  key={word}
                  word={word}
                  id={`id_${index + 1}`}
                  index={index + 1}
                />
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
              <Trans>Next</Trans>
            </Button>
          </Container>
        </Flex>
      </Container>
    </LayoutHero>
  );
}
