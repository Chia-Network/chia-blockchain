import React from 'react';
import { get } from 'lodash';
import { Controller, useFormContext } from 'react-hook-form';
import { Trans } from '@lingui/macro';
import { useGetFeeEstimateQuery } from '@chia/api-react';
import {
  Fee,
  Flex,
  mojoToChiaLocaleString,
  useLocale,
} from '@chia/core';
import {
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Select as MaterialSelect,
  SelectProps,
  Typography,
} from '@mui/material';
import ArrowDropDownIcon from '@mui/icons-material/ArrowDropDown';
import useMode from '../../hooks/useMode';
import Mode from '../../constants/Mode';

type Props = SelectProps & {
  hideError?: boolean;
  name: string;
};

function Select(props: Props) {
  const { name: controllerName, value: controllerValue, onTypeChange, children, ...rest } = props;
  const { control, errors, setValue } = useFormContext();
  const errorMessage = get(errors, controllerName);

  return (
    <Controller
      name={controllerName}
      control={control}
      render={({ field: { onChange, onBlur, value, name, ref } }) => (
        <MaterialSelect
          onChange={(event, ...args) => {
            onChange(event, ...args);
            if (props.onChange) {
              props.onChange(event, ...args);
            }
            if (event.target.value == "custom") {
              onTypeChange("custom");
              setValue(controllerName, '');
            } else {
              onTypeChange("dropdown")
            }
          }}
          onBlur={onBlur}
          value={value}
          name={name}
          ref={ref}
          error={!!errorMessage}
          {...rest}
        >
          {children}
        </MaterialSelect>
      )}
    />
  );
}

export default function EstimatedFee(props: FeeProps) {
  const { name, txType, required, ...rest } = props;
  const { data: ests, isLoading: isFeeLoading, error } = useGetFeeEstimateQuery({"targetTimes": [60, 120, 300], "cost": 1});
  const [estList, setEstList] = React.useState([]);
  const [inputType, setInputType] = React.useState("dropdown");
  const mode = useMode();
  const [selectOpen, setSelectOpen] = React.useState(false);
  const [locale] = useLocale();

  const maxBlockCostCLVM = 11000000000;
  const offersAcceptsPerBlock = 500;

  const txCostEstimates = {
      walletSendXCH: Math.floor(maxBlockCostCLVM / 1170),
      createOffer: Math.floor(maxBlockCostCLVM / offersAcceptsPerBlock),
      sellNFT: Math.floor(maxBlockCostCLVM / 92),
      createPoolingWallet: Math.floor(maxBlockCostCLVM / 462)  // JOIN_POOL in GUI = create pooling wallet
  }

  const multiplier = txCostEstimates[txType];

  function formatEst(number, multiplier, locale) {
    let num = (Math.round(number * multiplier * (10**(-4)))) * (10**(4));
    let formatNum = mojoToChiaLocaleString(num, locale);
    return (formatNum);
  }

  if (!isFeeLoading && ests && estList?.length == 0) {
    const estimateList = ests.estimates;
    const targetTimes = ests.targetTimes;
    if (estimateList[0] == 0 && estimateList[1] == 0 && estimateList[2] == 0) {
      setInputType("classic");
    }
    const est0 = formatEst(estimateList[0], multiplier, locale);
    const est1 = formatEst(estimateList[1], multiplier, locale);
    const est2 = formatEst(estimateList[2], multiplier, locale);
    setEstList(current => [...current, { time: "Likely in " + targetTimes[0] + " seconds", estimate: est0 }]);
    setEstList(current => [...current, { time: "Likely in " + (targetTimes[1] / 60) + " minutes", estimate: est1 }]);
    setEstList(current => [...current, { time: "Likely over " + (targetTimes[2] / 60) + " minutes", estimate: est2 }]);
  }

  const handleSelectOpen = () => {
    setSelectOpen(true);
  };

  const handleSelectClose = () => {
    setSelectOpen(false);
  };

  function showSelect() {
    return (
      <div>
        <InputLabel required={required} color="secondary">Fee</InputLabel>
        <Select name={name} onTypeChange={setInputType} open={selectOpen} onOpen={handleSelectOpen} onClose={handleSelectClose} {...rest}>
          {estList.map((option) => (
            <MenuItem
              value={String(option.estimate)}
              key={option.time}
            >
              <Flex flexDirection="row" flexGrow={1} justifyContent="space-between" alignItems="center">
                <Flex>
                  <Trans>{option.estimate} TXCH</Trans>
                </Flex>
                <Flex alignSelf="center">
                  <Trans><Typography color="textSecondary" fontSize="small">{option.time}</Typography></Trans>
                </Flex>
              </Flex>
            </MenuItem>
          ))}
          <MenuItem
            value="custom"
            key="custom"
          >
            Enter a custom fee...
          </MenuItem>
        </Select>
      </div>
    )
  }

  function showInput() {
    function showDropdown() {
      setSelectOpen(true);
      setInputType("dropdown");
    }

    return (
      <Flex flexDirection="row">
        <Flex flexGrow={1}>
          <Fee
            name={name}
            type="text"
            variant="filled"
            label={<Trans>Fee</Trans>}
            fullWidth
            required={required}
            autoFocus
            color="secondary"
            {...rest}
          />
        </Flex>
        <Flex alignSelf="center">
          <IconButton onClick={showDropdown}>
            <ArrowDropDownIcon />
          </IconButton>
        </Flex>
      </Flex>
    )
  }

  if (!error && (mode[0] === Mode.FARMING) && (inputType !== "classic")) {
    return (
      <Flex>
        <FormControl variant="filled" fullWidth>
          {inputType === "dropdown" ? showSelect() : showInput()}
        </FormControl>
      </Flex>
    );
  } else {
    return (
      <Flex>
        <FormControl variant="filled" fullWidth>
          <Fee
            name={name}
            type="text"
            variant="filled"
            label={<Trans>Fee</Trans>}
            fullWidth
            required={required}
            color="secondary"
            {...rest}
          />
        </FormControl>
      </Flex>
    )
  }
};
