import BigNumber from 'bignumber.js';
import Unit from '../constants/Unit';
import chiaFormatter from './chiaFormatter';

export default function mojoToChia(mojo: string | number | BigNumber): BigNumber {
  return chiaFormatter(mojo, Unit.MOJO)
    .to(Unit.CHIA)
    .toBigNumber();
}