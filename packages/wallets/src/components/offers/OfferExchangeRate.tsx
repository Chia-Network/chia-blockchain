import React, { useMemo } from "react";
import {
  Flex
} from '@chia/core';
import {
  TextField,
  Typography,
} from '@material-ui/core';
import { ImportExport } from '@material-ui/icons';
import { AssetIdMapEntry } from '../../hooks/useAssetIdName';
import { WalletType } from '@chia/api';

type Props = {
  makerAssetInfo: AssetIdMapEntry;
  takerAssetInfo: AssetIdMapEntry;
  makerExchangeRate: number;
  takerExchangeRate: number;
};

export default function OfferExchangeRate(props: Props) {
  const { makerAssetInfo, takerAssetInfo, makerExchangeRate, takerExchangeRate } = props;

  const [makerDisplayRate, takerDisplayRate] = useMemo(() => {
    return [
      {rate: makerExchangeRate, walletType: makerAssetInfo.walletType, counterCurrencyName: takerAssetInfo.displayName},
      {rate: takerExchangeRate, walletType: takerAssetInfo.walletType, counterCurrencyName: makerAssetInfo.displayName}
    ].map(({rate, walletType, counterCurrencyName}) => {
      let displayRate = '';

      if (Number.isInteger(rate)) {
        displayRate = `${rate}`;
      }
      else {
        const fixed = rate.toFixed(walletType === WalletType.STANDARD_WALLET ? 9 : 12);

        // remove trailing zeros
        displayRate = fixed.replace(/\.0+$/, '');
      }
      return `${displayRate} ${counterCurrencyName}`;
    });
  }, [makerAssetInfo, takerAssetInfo, makerExchangeRate, takerExchangeRate]);

  return (
    <Flex flexDirection="row">
      <Flex flexDirection="row" flexGrow={1} justifyContent="flex-end" gap={3} style={{width: '45%'}}>
        <Flex alignItems="baseline" gap={1}>
          <Typography variant="subtitle1" noWrap>1 {makerAssetInfo.displayName} =</Typography>
          <TextField
            key={`${makerExchangeRate}-${takerAssetInfo.displayName}`}
            variant="outlined"
            size="small"
            defaultValue={makerDisplayRate}
            InputProps={{
              readOnly: true,
            }}
            fullWidth={false}
          />
        </Flex>
      </Flex>
      <Flex flexDirection="column" alignItems="center" justifyContent="center" style={{width: '2em'}}>
        <ImportExport style={{transform: 'rotate(90deg)'}} />
      </Flex>
      <Flex flexDirection="row" gap={3} flexGrow={1} style={{width: '45%'}}>
        <Flex alignItems="baseline" gap={1}>
          <TextField
            key={`${takerExchangeRate}-${makerAssetInfo.displayName}`}
            variant="outlined"
            size="small"
            defaultValue={takerDisplayRate}
            InputProps={{
              readOnly: true,
            }}
            fullWidth={false}
          />
          <Typography variant="subtitle1" noWrap>= 1 {takerAssetInfo.displayName}</Typography>
        </Flex>
      </Flex>
    </Flex>
  );
}

OfferExchangeRate.defaultProps = {
};
