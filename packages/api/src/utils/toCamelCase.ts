import { camelCase, transform, isArray, isObject } from 'lodash';

export default function toCamelCase(object: Object): Object {
  return transform(object, (acc, value, key, target) => {
    const newKey = isArray(target) || key.indexOf('_') === -1 ? key : camelCase(key);
    
    acc[newKey] = isObject(value) ? toCamelCase(value) : value;
  });
}
