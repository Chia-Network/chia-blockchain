import BigNumber from 'bignumber.js';
import type Unit from '../constants/Unit';
import UnitValue from '../constants/UnitValue';
import bigNumberToLocaleString from './bigNumberToLocaleString';

class Chia {
  private _value: BigNumber;
  private _unit: Unit

  constructor(value: number | string | BigNumber, unit: Unit) {
    const stringValue = value === '' || value === '.' || value === null || value === undefined
      ? '0'
      : value.toString();

    this._value = new BigNumber(stringValue);
    this._unit = unit;
  }

  get value(): BigNumber {
    return this._value;
  }

  get unit(): Unit {
    return this._unit;
  }

  to(newUnit: Unit) {
    const fromUnitValue = UnitValue[this.unit];
    const toUnitValue = UnitValue[newUnit];
  
    const amountInFromUnit = this.value.times(fromUnitValue.toString());
    const newValue = amountInFromUnit.div(toUnitValue.toString());

    return new Chia(newValue, newUnit);
  }

  toFixed(decimals: number): string {
    return this.value.toFixed(decimals);
  }

  toString(): string {
    return this.value.toString();
  }

  toBigNumber(): BigNumber {
    return this.value;
  }

  toLocaleString(locale?: string): string {
    return bigNumberToLocaleString(this.value, locale);
  }
}

export default function chiaFormatter(value: number | string | BigNumber, unit: Unit) {
  return new Chia(value, unit);
}
