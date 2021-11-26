import Big from 'big.js';
import Unit from '../constants/Unit';
import chiaFormatter from './chiaFormatter';

export default function mojoToCATLocaleString(mojo: string | number | Big) {
  return chiaFormatter(Number(mojo), Unit.MOJO)
    .to(Unit.CAT)
    .toLocaleString();
}