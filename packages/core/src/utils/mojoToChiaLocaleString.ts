import BigNumber from 'bignumber.js';
import Unit from '../constants/Unit';
import chiaFormatter from './chiaFormatter';

export default function mojoToChiaLocaleString(mojo: string | number | BigNumber, locale?: string) {
  return chiaFormatter(Number(mojo), Unit.MOJO)
    .to(Unit.CHIA)
    .toLocaleString(locale);
}