import Big from 'big.js';
import Unit from '../constants/Unit';
import chiaFormatter from './chiaFormatter';

export default function mojoToCAT(mojo: string | number | Big): string {
  return chiaFormatter(mojo, Unit.MOJO)
    .to(Unit.CAT)
    .toString();
}