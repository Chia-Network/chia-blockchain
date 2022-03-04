import BigNumber from 'bignumber.js';
import Unit from '../constants/Unit';
import chiaFormatter from './chiaFormatter';

export default function catToMojo(cat: string | number | BigNumber): BigNumber {
  return chiaFormatter(cat, Unit.CAT)
    .to(Unit.MOJO)
    .toBigNumber();
}