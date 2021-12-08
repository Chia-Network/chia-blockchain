import Big from 'big.js';
import Unit from '../constants/Unit';
import chiaFormatter from './chiaFormatter';

export default function chiaToMojo(chia: string | number | Big): number {
  return chiaFormatter(chia, Unit.CHIA)
    .to(Unit.MOJO)
    .toNumber();
}