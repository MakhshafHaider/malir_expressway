export const normalizePlate = (value: string): string =>
  value.replace(/[\s\-]/g, '').toUpperCase();
