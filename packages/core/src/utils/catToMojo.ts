import Big from 'big.js';
import Unit from '../constants/Unit';
import chiaFormatter from './chiaFormatter';

export default function catToMojo(cat: string | number | Big): number {
  return chiaFormatter(cat, Unit.CAT)
    .to(Unit.MOJO)
    .toNumber();
}