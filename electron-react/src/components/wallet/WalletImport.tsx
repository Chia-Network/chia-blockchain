import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import {
  TextField,
  Typography,
  Container,
  Button,
  Grid,
} from '@material-ui/core';
import { ArrowBackIos as ArrowBackIosIcon } from '@material-ui/icons';
import { useSelector, useDispatch } from 'react-redux';
import { useHistory } from 'react-router';
import { Flex, Logo } from '@chia/core';
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
    /* TODO: (Zlatko)
    Pre fill Trie (src/util/trie.js) with words from english.txt
    Find current input in trie and either show mnemonic suggestion | error 
    */
    if (!e.target) {
      return;
    }

    const id = `${e.target.id}`;
    const clean_id = id.replace('id_', '');
    const int_val = Number.parseInt(clean_id, 10) - 1;
    const data = {
      word: e.target.value,
      id: int_val,
    };
    dispatch(mnemonic_word_added(data));
  }
  const indents = [];
  for (let i = 0; i < 24; i += 1) {
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
    const hasEmptyElement = mnemonic.find((element) => element === '');
    if (!hasEmptyElement) {
      dispatch(unselectFingerprint());
      history.push('/wallet/restore');
    }
  }

  return (
    <LayoutHero
      header={
        <ArrowBackIosIcon
          onClick={handleBack}
          fontSize="large"
          color="secondary"
        />
      }
    >
      <Container maxWidth="lg">
        <Flex flexDirection="column" gap={3} alignItems="center">
          <Logo />
          <Typography variant="h4" component="h1" gutterBottom>
            <Trans id="WalletImport.title">Import Wallet from Mnemonics</Trans>
          </Typography>
          <Typography variant="subtitle1" align="center">
            <Trans id="WalletImport.description">
              Enter the 24 word mnemonic that you have saved in order to restore
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
              <Trans id="WalletImport.next">Next</Trans>
            </Button>
          </Container>
        </Flex>
      </Container>
    </LayoutHero>
  );
}
