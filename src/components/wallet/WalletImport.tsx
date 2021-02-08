import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import {
  TextField,
  Typography,
  Container,
  Button,
  Grid,
  TextFieldProps,
} from '@material-ui/core';
import { Autocomplete } from '@material-ui/lab';
import { ArrowBackIos as ArrowBackIosIcon } from '@material-ui/icons';
import { useSelector, useDispatch } from 'react-redux';
import { useHistory } from 'react-router';
import { Flex, Logo } from '@chia/core';
import { matchSorter } from 'match-sorter';
import LayoutHero from '../layout/LayoutHero';
import { mnemonic_word_added, resetMnemonic } from '../../modules/mnemonic';
import { unselectFingerprint } from '../../modules/message';
import type { RootState } from '../../modules/rootReducer';
import english from '../../util/english';

const options = english.map((item) => item.word);

const filterOptions = (options: string[], { inputValue }: { inputValue: string }) =>
  matchSorter(options, inputValue, {
    threshold: matchSorter.rankings.STARTS_WITH,
  });

type MnemonicFieldProps = {
  onChangeValue: (value: string) => void;
};

function MnemonicField(props: TextFieldProps & MnemonicFieldProps) {
  const { onChangeValue, error, autoFocus, label } = props;

  return (
    <Grid item xs={2}>
      <Autocomplete
        id={props.id}
        options={options}
        filterOptions={filterOptions}
        onChange={(_e, newValue) => onChangeValue(newValue || '')}
        renderInput={(params) => (
          <TextField
            autoComplete="off"
            variant="outlined"
            margin="normal"
            color="primary"
            label={label}
            error={error}
            autoFocus={autoFocus}
            defaultValue={props.value}
            onChange={(e) => onChangeValue(e.target.value)}
            {...params}
          />
        )}
        freeSolo
        fullWidth
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

  function handleTextFieldChange(id: number, word: string) {
    dispatch(mnemonic_word_added({
      word,
      id,
    }));
  }

  const indents = [];
  for (let i = 0; i < 24; i += 1) {
    const focus = i === 0;
    indents.push(
      <MnemonicField
        onChangeValue={(value) => handleTextFieldChange(i, value)}
        key={i}
        error={
          (props.submitted && mnemonic_state.mnemonic_input[i] === '') ||
          mnemonic_state.mnemonic_input[i] === incorrect_word
        }
        value={mnemonic_state.mnemonic_input[i]}
        autoFocus={focus}
        id={`id_${i + 1}`}
        label={i + 1}
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
            <Trans>Import Wallet from Mnemonics</Trans>
          </Typography>
          <Typography variant="subtitle1" align="center">
            <Trans>
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
              <Trans>Next</Trans>
            </Button>
          </Container>
        </Flex>
      </Container>
    </LayoutHero>
  );
}
