/**
 * `parseApiTimestamp` exists because ECMAScript reads a designator-less
 * date-time as local time. These tests run the same assertions from two
 * different viewer timezones, so a helper that quietly falls back to local
 * parsing cannot pass by accident on a machine that happens to be in UTC.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { parseApiTimestamp } from './datetime';

const TIMEZONES = ['UTC', 'Asia/Taipei', 'America/New_York'];

let originalTimezone: string | undefined;

beforeEach(() => {
  originalTimezone = process.env.TZ;
});

afterEach(() => {
  process.env.TZ = originalTimezone;
});

describe('parseApiTimestamp', () => {
  for (const timezone of TIMEZONES) {
    describe(`viewed from ${timezone}`, () => {
      beforeEach(() => {
        process.env.TZ = timezone;
      });

      it('reads a designator-less timestamp as UTC', () => {
        expect(parseApiTimestamp('2026-08-13T16:29:50').toISOString()).toBe(
          '2026-08-13T16:29:50.000Z',
        );
      });

      it('keeps fractional seconds on a designator-less timestamp', () => {
        expect(parseApiTimestamp('2026-08-13T16:29:50.123456').toISOString()).toBe(
          '2026-08-13T16:29:50.123Z',
        );
      });

      it('reads a space-separated timestamp as UTC', () => {
        // What SQLite hands back, and what str(datetime) produces.
        expect(parseApiTimestamp('2026-08-13 16:29:50').toISOString()).toBe(
          '2026-08-13T16:29:50.000Z',
        );
      });

      it('honours a Z designator', () => {
        expect(parseApiTimestamp('2026-08-13T16:29:50Z').toISOString()).toBe(
          '2026-08-13T16:29:50.000Z',
        );
      });

      it('honours a numeric offset rather than overriding it with UTC', () => {
        expect(parseApiTimestamp('2026-08-14T00:29:50+08:00').toISOString()).toBe(
          '2026-08-13T16:29:50.000Z',
        );
        expect(parseApiTimestamp('2026-08-13T12:29:50-04:00').toISOString()).toBe(
          '2026-08-13T16:29:50.000Z',
        );
      });

      it('leaves a date-only value alone, which is already UTC', () => {
        expect(parseApiTimestamp('2026-08-13').toISOString()).toBe(
          '2026-08-13T00:00:00.000Z',
        );
      });

      it('tolerates surrounding whitespace', () => {
        expect(parseApiTimestamp('  2026-08-13T16:29:50  ').toISOString()).toBe(
          '2026-08-13T16:29:50.000Z',
        );
      });

      it('reports an unparseable value instead of inventing an instant', () => {
        expect(Number.isNaN(parseApiTimestamp('not a timestamp').getTime())).toBe(true);
      });
    });
  }
});
