import BigNumber from 'bignumber.js';

const complexNumber = 1234567.0123456789;

export default function bigNumberToLocaleString(value: BigNumber, locale?: string): string {
    const formatter = Intl.NumberFormat(locale);
    if (!formatter) {
      throw new Error(`Formatter for ${locale} is not supported`);
    }

    const decimalFormatter = new Intl.NumberFormat(locale, { 
      maximumFractionDigits: 12,
    });
    if (!decimalFormatter) {
      throw new Error(`Decimal formatter for ${locale} is not supported`);
    }

    const parts = decimalFormatter.formatToParts(complexNumber);

    const decimalPart = parts.find(part => part.type === 'decimal');
    const groupPart = parts.find(part => part.type === 'group');

    const reversedParts = parts.slice().reverse();
    const integerPart = reversedParts.find(part => part.type === 'integer');

    const format = {
      prefix: '',
      decimalSeparator: decimalPart?.value ?? '.',
      groupSeparator: groupPart?.value ?? ',',
      groupSize: integerPart?.value?.length ?? 3,
      secondaryGroupSize: 0,
      fractionGroupSeparator: ' ',
      fractionGroupSize: 0,
      suffix: ''
    };

    return value.toFormat(format);
}
