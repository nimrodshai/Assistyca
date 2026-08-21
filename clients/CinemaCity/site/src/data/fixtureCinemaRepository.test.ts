import { describe, expect, test } from 'vitest';
import {
  buildSeatMap,
  calculateSubtotal,
  calculateTotal,
  filterMovies,
  fixtureData,
  getOpenStatus,
  isDraftExpired,
  normalizeCinemas,
  normalizeMovies,
  trimSeatsForTicketCount,
} from './fixtureCinemaRepository';

describe('Cinema City fixture helpers', () => {
  test('filters children movies and Hebrew language screenings', () => {
    const results = filterMovies(normalizeMovies(), fixtureData.screenings, {
      audience: 'children',
      language: 'עברית',
      status: 'all',
    });
    expect(results.map((movie) => movie.slug)).toEqual(
      expect.arrayContaining(['coyote-vs-acme-hebrew', 'pout-pout-fish-hebrew']),
    );
  });

  test('filters by premium experience without changing fixture content', () => {
    const results = filterMovies(normalizeMovies(), fixtureData.screenings, {
      experience: 'onyx',
      status: 'all',
    });
    expect(results.map((movie) => movie.slug)).toEqual(expect.arrayContaining(['the-odyssey', 'la-la-land-10th-anniversary']));
  });

  test('calculates totals with service fee and demo voucher cap', () => {
    const screening = fixtureData.screenings.find((item) => item.id === 'scr-spider-glilot-20260821-2030')!;
    const quantities = { adult: 2 };
    expect(calculateSubtotal(screening, quantities)).toBe(88);
    expect(calculateTotal(screening, quantities, 20)).toBeCloseTo(72.9);
  });

  test('detects expired drafts and trims excess seats after quantity changes', () => {
    expect(isDraftExpired({ ticketQuantities: {}, selectedSeatIds: [], discount: 0, expiresAt: '2026-01-01T00:00:00Z' })).toBe(true);
    expect(trimSeatsForTicketCount(['F6', 'F7', 'F8'], 2)).toEqual(['F6', 'F7']);
  });

  test('generates accessible and occupied seat records from compact definitions', () => {
    const seatMap = buildSeatMap(fixtureData.seatMaps[0]);
    expect(seatMap.seats.find((seat) => seat.id === 'H1')?.kind).toBe('accessible');
    expect(seatMap.seats.find((seat) => seat.id === 'A4')?.status).toBe('occupied');
    expect(seatMap.seats).toHaveLength(80);
  });

  test('calculates open status against Asia/Jerusalem fixture hours', () => {
    const glilot = normalizeCinemas().find((cinema) => cinema.slug === 'glilot')!;
    expect(getOpenStatus(glilot, new Date('2026-08-21T18:00:00+03:00')).label).toBe('פתוח עכשיו');
  });
});
