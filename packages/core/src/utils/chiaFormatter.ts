import Big from 'big.js';
import { trimEnd } from 'lodash';
import type Unit from '../constants/Unit';
import UnitFractionDigits from '../constants/UnitFractionDigits';
import UnitValue from '../constants/UnitValue';

Big.strict = true;

class Chia {
  private _value: Big;
  private _unit: Unit

  constructor(value: number | string | Big, unit: Unit) {
    const stringValue = value === '' || value === null || value === undefined
      ? '0'
      : value.toString();

    this._value = new Big(stringValue);
    this._unit = unit;
  }

  get value(): Big {
    return new Big(this._value);
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

  toFixed(decimals: number): Big {
    return this.value.toFixed(decimals);
  }

  toString(): string {
    return this.value.toString();
  }

  toLocaleString(locale?: string): string {
    const formatter = Intl.NumberFormat(locale);
    if (!formatter) {
      throw new Error(`Formater for ${locale} is not supported`);
    }

    const maximumFractionDigits = UnitFractionDigits[this.unit];
    if (!maximumFractionDigits) {
      return formatter.format(BigInt(this.toFixed(0).toString()))
    }

    const withDecimal = this.toFixed(maximumFractionDigits);
    const [left, right] = withDecimal.split('.');

    const rightFormated = trimEnd(right, '0');
    if (!rightFormated.length) {
      return formatter.format(BigInt(left));
    }

    const separatorPart = formatter.formatToParts(1.1).find((part) => part.type === 'decimal');
    if (!separatorPart) {
      throw new Error(`Separator is not supported for ${locale}`);
    }
    
    const separator = separatorPart.value;

    const decimalFormatter = new Intl.NumberFormat(locale, {
      useGrouping: false
    });
    if (!decimalFormatter) {
      throw new Error(`Decimal formater for ${locale} is not supported`);
    }

    return `${formatter.format(BigInt(left))}${separator}${decimalFormatter.format(BigInt(right))}`;
  }
}

export default function chiaFormatter(value: number | string | Big, unit: Unit) {
  return new Chia(value, unit);
}
