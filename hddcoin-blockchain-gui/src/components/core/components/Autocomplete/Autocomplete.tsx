import React from 'react';
import { TextField, TextFieldProps } from '@material-ui/core';
import { get } from 'lodash';
import {
  Autocomplete as MaterialAutocomplete,
  AutocompleteProps,
} from '@material-ui/lab';
import { matchSorter } from 'match-sorter';
import { useController, useFormContext } from 'react-hook-form';
import type { ReactRules } from '../TextField/TextField';

const filterOptions = (
  options: string[],
  { inputValue }: { inputValue: string },
) =>
  matchSorter(options, inputValue, {
    threshold: matchSorter.rankings.STARTS_WITH,
  });

type Props = TextFieldProps &
  AutocompleteProps<string, false, false, true> & {
    name: string;
    defaultValue?: any;
    // shouldUnregister?: boolean;
    fullWidth?: boolean;
    freeSolo?: boolean;
    rules?: ReactRules<typeof MaterialAutocomplete>;
    renderInput?: any;
  };

export default function Autocomplete(props: Props) {
  const {
    name,
    defaultValue,
    rules,
    options,
    // shouldUnregister,
    fullWidth,
    freeSolo,
    forcePopupIcon,
    onChange: defaultOnChange,
    ...rest
  } = props;
  const { control, errors } = useFormContext();
  const {
    field: { onChange, onBlur, value, ref },
    /*
    fieldState: {
      error,
    },
    */
  } = useController({
    name,
    control,
    defaultValue,
    rules,
    // shouldUnregister,
  });

  function handleChange(newValue: any) {
    const updatedValue = newValue || '';
    onChange(updatedValue);

    if (defaultOnChange) {
      defaultOnChange(updatedValue);
    }
  }

  const errorMessage = get(errors, name);

  return (
    <MaterialAutocomplete
      options={options}
      filterOptions={filterOptions}
      onChange={(_e, newValue) => handleChange(newValue)}
      value={value}
      renderInput={(params) => (
        <TextField
          autoComplete="off"
          error={errorMessage}
          onChange={(e) => handleChange(e.target.value)}
          onBlur={onBlur}
          inputRef={ref}
          {...rest}
          {...params}
        />
      )}
      freeSolo={freeSolo}
      fullWidth={fullWidth}
      forcePopupIcon={forcePopupIcon}
    />
  );
}
