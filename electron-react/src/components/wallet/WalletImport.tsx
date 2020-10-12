import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import { Typography, Container, Button, Grid } from '@material-ui/core';
import { ArrowBackIos as ArrowBackIosIcon } from '@material-ui/icons';
import { useSelector, useDispatch } from 'react-redux';
import { useHistory } from 'react-router';
import TextField from '../form/TextField';
import Brand from '../brand/Brand';
import Flex from '../flex/Flex';
import Link from '../router/Link';
import LayoutHero from '../layout/LayoutHero';
import { mnemonic_word_added, resetMnemonic } from '../../modules/mnemonic';
import { unselectFingerprint } from '../../modules/message';
import type { RootState } from '../../modules/rootReducer';

function MnemonicField(props: any) {
  return (
    <Grid item xs={2}>
      <TextField
        autoComplete="off"
        variant="outlined"
        margin="normal"
        fullWidth
        color="primary"
        id={props.id}
        label={props.index}
        error={props.error}
        autoFocus={props.autofocus}
        defaultValue={props.value}
        onChange={props.onChange}
      />
    </Grid>
  );
}

function Iterator(props: any) {
  const dispatch = useDispatch();
  const mnemonic_state = useSelector(
    (state: RootState) => state.mnemonic_state,
  );
  const incorrect_word = useSelector(
    (state: RootState) => state.mnemonic_state.incorrect_word,
  );

  function handleTextFieldChange(
    e: InputEvent & { target: { id: number; value: string } },
  ) {
    if (!e.target) {
      return;
    }

    const id = `${e.target.id}`;
    const clean_id = id.replace('id_', '');
    const int_val = parseInt(clean_id) - 1;
    const data = {
      word: e.target.value,
      id: int_val,
    };
    dispatch(mnemonic_word_added(data));
  }
  const indents = [];
  for (let i = 0; i < 24; i++) {
    const focus = i === 0;
    indents.push(
      <MnemonicField
        onChange={handleTextFieldChange}
        key={i}
        error={
          (props.submitted && mnemonic_state.mnemonic_input[i] === '') ||
          mnemonic_state.mnemonic_input[i] === incorrect_word
        }
        value={mnemonic_state.mnemonic_input[i]}
        autofocus={focus}
        id={`id_${i + 1}`}
        index={i + 1}
      />,
    );
  }
  return <>{indents}</>;
}

export default function WalletImport() {
  const dispatch = useDispatch();
  const history = useHistory();
  const [submitted, setSubmitted] = useState<boolean>(false);
  const mnemonic = useSelector(
    (state: RootState) => state.mnemonic_state.mnemonic_input,
  );

  function handleBack() {
    dispatch(resetMnemonic());

    history.push('/');
  }

  function handleSubmit() {
    setSubmitted(true);
    for (let i = 0; i < mnemonic.length; i++) {
      if (mnemonic[i] === '') {
        return;
      }
    }
    dispatch(unselectFingerprint());
    history.push('/wallet/restore');
  }

  return (
    <LayoutHero
      header={(
        <ArrowBackIosIcon
          onClick={handleBack}
          fontSize="large"
          color="secondary"
        />
      )}
    >
      <Container maxWidth="lg">
        <Flex flexDirection="column" gap={3} alignItems="center">
          <Brand />
          <Typography variant="h4" component="h1" gutterBottom>
            <Trans id="WalletImport.title">
              Import Wallet from Mnemonics
            </Trans>
          </Typography>
          <Typography variant="subtitle1" align="center">
            <Trans id="WalletImport.description">
              Enter the 24 word mmemonic that you have saved in order to restore
              your Chia wallet.
            </Trans>
          </Typography>
          <Grid container spacing={2}>
            <Iterator submitted={submitted} />
          </Grid>
          <Container maxWidth="xs">
            <Button
              onClick={handleSubmit}
              type="submit"
              variant="contained"
              color="primary"
              fullWidth
            >
              <Trans id="WalletImport.next">
                Next
              </Trans>
            </Button>
          </Container>
        </Flex>
      </Container>
    </LayoutHero>
  );
}
