import fixtureJson from './fixture-data.json';
import { brandAsset, cinemaAssets, experienceAssets, movieAssets } from './assetManifest';
import type {
  BookingDraft,
  Cinema,
  CinemaRepository,
  Experience,
  ExperienceRecord,
  FixtureData,
  HomePayload,
  Movie,
  MovieFilters,
  Order,
  Screening,
  ScreeningQuery,
  Seat,
  SeatMap,
  SeatMapDefinition,
} from './types';

const fixture = fixtureJson as FixtureData;

let repositoryDelayMs = import.meta.env.MODE === 'test' ? 0 : 180;

export function setRepositoryDelay(ms: number) {
  repositoryDelayMs = ms;
}

function delay() {
  return new Promise((resolve) => window.setTimeout(resolve, repositoryDelayMs));
}

export function toLocalDate(iso: string) {
  return iso.slice(0, 10);
}

export function formatTime(iso: string) {
  return new Intl.DateTimeFormat('he-IL', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'Asia/Jerusalem',
  }).format(new Date(iso));
}

export function formatDate(isoOrDate: string, weekday = true) {
  return new Intl.DateTimeFormat('he-IL', {
    weekday: weekday ? 'short' : undefined,
    day: 'numeric',
    month: 'short',
    timeZone: 'Asia/Jerusalem',
  }).format(new Date(`${isoOrDate.slice(0, 10)}T12:00:00+03:00`));
}

export function formatCurrency(amount: number) {
  return new Intl.NumberFormat('he-IL', { style: 'currency', currency: 'ILS' }).format(amount);
}

export function experienceLabel(experience: Experience) {
  const labels: Record<Experience, string> = {
    standard: 'רגיל',
    vip: 'VIP',
    prime: 'PRIME',
    onyx: 'ONYX',
  };
  return labels[experience];
}

export function normalizeMovies(): Movie[] {
  return fixture.movies.map((movie) => ({
    ...movie,
    posterUrl: movieAssets[movie.id]?.posterUrl ?? '',
    backdropUrl: movieAssets[movie.id]?.backdropUrl ?? movieAssets[movie.id]?.posterUrl ?? '',
  }));
}

export function normalizeCinemas(): Cinema[] {
  return fixture.cinemas.map((cinema) => ({
    ...cinema,
    imageUrl: cinemaAssets[cinema.id]?.imageUrl ?? '',
  }));
}

export function normalizeExperiences(): ExperienceRecord[] {
  return fixture.experiences.map((experience) => ({
    ...experience,
    imageUrl: experienceAssets[experience.id]?.imageUrl ?? '',
  }));
}

export function buildSeatMap(definition: SeatMapDefinition): SeatMap {
  const seats: Seat[] = [];
  for (const row of definition.rowLabels) {
    for (let number = 1; number <= definition.seatsPerRow; number += 1) {
      const id = `${row}${number}`;
      const kind = definition.accessibleSeatIds.includes(id)
        ? 'accessible'
        : definition.companionSeatIds.includes(id)
          ? 'companion'
          : definition.premiumSeatIds.includes(id)
            ? 'premium'
            : 'standard';
      seats.push({
        id,
        row,
        number,
        kind,
        status: definition.occupiedSeatIds.includes(id) ? 'occupied' : 'available',
      });
    }
  }
  return { ...definition, seats };
}

export function calculateSubtotal(
  screening: Screening,
  ticketQuantities: BookingDraft['ticketQuantities'],
) {
  return screening.ticketTypes.reduce((sum, ticketType) => {
    return sum + (ticketQuantities[ticketType.id] ?? 0) * ticketType.price;
  }, 0);
}

export function calculateTotal(
  screening: Screening,
  ticketQuantities: BookingDraft['ticketQuantities'],
  discount = 0,
) {
  const subtotal = calculateSubtotal(screening, ticketQuantities);
  const cappedDiscount = Math.min(discount, subtotal);
  return Math.max(0, subtotal + screening.serviceFee - cappedDiscount);
}

export function totalTickets(ticketQuantities: BookingDraft['ticketQuantities']) {
  return Object.values(ticketQuantities).reduce((sum, count) => sum + count, 0);
}

export function isDraftExpired(draft: BookingDraft, now = Date.now()) {
  return Boolean(draft.expiresAt && new Date(draft.expiresAt).getTime() <= now);
}

export function trimSeatsForTicketCount(selectedSeatIds: string[], ticketCount: number) {
  return selectedSeatIds.slice(0, ticketCount);
}

export function filterMovies(movies: Movie[], screenings: Screening[], filters: MovieFilters = {}) {
  const query = filters.query?.trim().toLowerCase();
  const filtered = movies.filter((movie) => {
    const matchesQuery =
      !query ||
      movie.titleHe.toLowerCase().includes(query) ||
      movie.titleOriginal.toLowerCase().includes(query) ||
      movie.genres.some((genre) => genre.toLowerCase().includes(query));
    const matchesStatus = !filters.status || filters.status === 'all' || movie.status === filters.status;
    const matchesGenre = !filters.genre || movie.genres.includes(filters.genre);
    const matchesLanguage =
      !filters.language ||
      movie.spokenLanguages.includes(filters.language) ||
      movie.subtitleLanguages.includes(filters.language);
    const matchesAudience = !filters.audience || filters.audience === 'all' || movie.audience === filters.audience;
    const matchesExperience =
      !filters.experience ||
      filters.experience === 'all' ||
      screenings.some((screening) => screening.movieId === movie.id && screening.experience === filters.experience);
    return matchesQuery && matchesStatus && matchesGenre && matchesLanguage && matchesAudience && matchesExperience;
  });

  if (filters.sort === 'title') {
    return filtered.sort((a, b) => a.titleHe.localeCompare(b.titleHe, 'he'));
  }
  if (filters.sort === 'release') {
    return filtered.sort((a, b) => b.releaseDate.localeCompare(a.releaseDate));
  }
  return filtered.sort((a, b) => {
    const nextA = screenings.find((screening) => screening.movieId === a.id)?.startsAt ?? '9999';
    const nextB = screenings.find((screening) => screening.movieId === b.id)?.startsAt ?? '9999';
    return nextA.localeCompare(nextB);
  });
}

export function getOpenStatus(cinema: Cinema, now = new Date()) {
  const dayKeys = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'];
  const formatter = new Intl.DateTimeFormat('en-US', {
    weekday: 'long',
    timeZone: 'Asia/Jerusalem',
  });
  const dayName = formatter.format(now).toLowerCase();
  const dayIndex = dayKeys.indexOf(dayName);
  const hours = cinema.weeklyHours[dayKeys[dayIndex]];
  if (!hours) return { label: 'סגור היום', state: 'muted' as const };

  const localTime = new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'Asia/Jerusalem',
  }).format(now);
  const close = hours.close === '00:00' ? '24:00' : hours.close;
  if (localTime >= hours.open && localTime <= close) return { label: 'פתוח עכשיו', state: 'success' as const };
  if (localTime < hours.open) return { label: `נפתח ב-${hours.open}`, state: 'warning' as const };
  return { label: 'סגור היום', state: 'muted' as const };
}

class FixtureCinemaRepository implements CinemaRepository {
  async getHome(): Promise<HomePayload> {
    await delay();
    const movies = normalizeMovies();
    const cinemas = normalizeCinemas();
    const experiences = normalizeExperiences();
    const featuredMovie = movies.find((movie) => movie.id === fixture.home.featuredMovieId) ?? movies[0];
    return {
      brand: { ...fixture.brand, logoSourceUrl: brandAsset },
      movies,
      cinemas,
      experiences,
      featuredMovie,
    };
  }

  async listMovies(filters?: MovieFilters): Promise<Movie[]> {
    await delay();
    return filterMovies(normalizeMovies(), fixture.screenings, filters);
  }

  async getMovie(slug: string): Promise<Movie | null> {
    await delay();
    return normalizeMovies().find((movie) => movie.slug === slug) ?? null;
  }

  async listCinemas(): Promise<Cinema[]> {
    await delay();
    return normalizeCinemas();
  }

  async getCinema(slug: string): Promise<Cinema | null> {
    await delay();
    return normalizeCinemas().find((cinema) => cinema.slug === slug) ?? null;
  }

  async listExperiences(): Promise<ExperienceRecord[]> {
    await delay();
    return normalizeExperiences();
  }

  async listScreenings(query: ScreeningQuery = {}): Promise<Screening[]> {
    await delay();
    const movies = normalizeMovies();
    const cinemas = normalizeCinemas();
    const movieId = query.movieId ?? movies.find((movie) => movie.slug === query.movieSlug)?.id;
    const cinemaId = query.cinemaId ?? cinemas.find((cinema) => cinema.slug === query.cinemaSlug)?.id;
    return fixture.screenings
      .filter((screening) => {
        const matchesMovie = !movieId || screening.movieId === movieId;
        const matchesCinema = !cinemaId || screening.cinemaId === cinemaId;
        const matchesDate = !query.date || toLocalDate(screening.startsAt) === query.date;
        const matchesExperience =
          !query.experience || query.experience === 'all' || screening.experience === query.experience;
        return matchesMovie && matchesCinema && matchesDate && matchesExperience;
      })
      .sort((a, b) => a.startsAt.localeCompare(b.startsAt));
  }

  async getScreening(id: string): Promise<Screening | null> {
    await delay();
    return fixture.screenings.find((screening) => screening.id === id) ?? null;
  }

  async getSeatMap(id: string): Promise<SeatMap | null> {
    await delay();
    const definition = fixture.seatMaps.find((seatMap) => seatMap.id === id);
    return definition ? buildSeatMap(definition) : null;
  }

  async findOrder(reference: string, email: string): Promise<Order | null> {
    await delay();
    const normalizedReference = reference.trim().toUpperCase();
    const normalizedEmail = email.trim().toLowerCase();
    return (
      fixture.orders.find(
        (order) => order.reference.toUpperCase() === normalizedReference && order.email.toLowerCase() === normalizedEmail,
      ) ?? null
    );
  }
}

export const cinemaRepository = new FixtureCinemaRepository();
export const fixtureData = fixture;
