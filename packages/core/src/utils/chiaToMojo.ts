import BigNumber from 'bignumber.js';
import Unit from '../constants/Unit';
import chiaFormatter from './chiaFormatter';

export default function chiaToMojo(chia: string | number | BigNumber): BigNumber {
  return chiaFormatter(chia, Unit.CHIA)
    .to(Unit.MOJO)
    .toBigNumber();
}