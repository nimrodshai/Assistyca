export type Experience = 'standard' | 'vip' | 'prime' | 'onyx';
export type Availability = 'available' | 'low' | 'sold-out';
export type MovieStatus = 'now-showing' | 'coming-soon';

export interface Brand {
  nameHe: string;
  taglineHe: string;
  logoSourceUrl: string;
}

export interface ExperienceRecord {
  id: Exclude<Experience, 'standard'>;
  nameHe: string;
  headingHe: string;
  descriptionHe: string;
  accent: 'gold' | 'teal' | 'sky';
  cinemaIds: string[];
  imageSourceUrl: string;
  imageUrl: string;
}

export interface Movie {
  id: string;
  slug: string;
  titleHe: string;
  titleOriginal: string;
  synopsisHe: string;
  genres: string[];
  runtimeMinutes: number;
  releaseDate: string;
  ageRestriction: string;
  status: MovieStatus;
  audience: 'general' | 'children';
  spokenLanguages: string[];
  subtitleLanguages: string[];
  badges: string[];
  posterUrl: string;
  backdropUrl: string;
  trailerUrl?: string;
  photosensitivityWarning?: string;
}

export interface Cinema {
  id: string;
  slug: string;
  nameHe: string;
  cityHe: string;
  addressHe: string;
  descriptionHe: string;
  imageUrl: string;
  mapUrl: string;
  phone?: string;
  weeklyHours: Record<string, { open: string; close: string } | null>;
  parkingHe: string;
  publicTransportHe: string;
  accessibilityHe: string;
  amenities: string[];
  experiences: Experience[];
}

export interface Screening {
  id: string;
  movieId: string;
  cinemaId: string;
  startsAt: string;
  hallNameHe: string;
  experience: Experience;
  spokenLanguage: string;
  subtitleLanguage?: string;
  availability: Availability;
  serviceFee: number;
  ticketTypes: TicketType[];
  seatMapId: string;
}

export interface TicketType {
  id: string;
  labelHe: string;
  noteHe?: string;
  price: number;
}

export interface Seat {
  id: string;
  row: string;
  number: number;
  kind: 'standard' | 'premium' | 'accessible' | 'companion';
  status: 'available' | 'occupied';
}

export interface SeatMapDefinition {
  id: string;
  rowLabels: string[];
  seatsPerRow: number;
  aislesAfterSeatNumbers: number[];
  premiumSeatIds: string[];
  accessibleSeatIds: string[];
  companionSeatIds: string[];
  occupiedSeatIds: string[];
}

export interface SeatMap extends SeatMapDefinition {
  seats: Seat[];
}

export interface BookingDraft {
  screeningId?: string;
  ticketQuantities: Record<string, number>;
  selectedSeatIds: string[];
  voucherCode?: string;
  discount: number;
  expiresAt?: string;
}

export interface Order {
  reference: string;
  email: string;
  fullName: string;
  phone: string;
  screeningId: string;
  ticketLines: Array<{ ticketTypeId: string; quantity: number; unitPrice: number }>;
  seatIds: string[];
  serviceFee: number;
  discount: number;
  total: number;
  status: 'confirmed' | 'cancelled';
  createdAt: string;
}

export interface MovieFilters {
  query?: string;
  status?: MovieStatus | 'all';
  genre?: string;
  language?: string;
  experience?: Experience | 'all';
  audience?: 'children' | 'all';
  sort?: 'soonest' | 'title' | 'release';
}

export interface ScreeningQuery {
  movieId?: string;
  movieSlug?: string;
  cinemaId?: string;
  cinemaSlug?: string;
  date?: string;
  experience?: Experience | 'all';
}

export interface HomePayload {
  brand: Brand;
  movies: Movie[];
  cinemas: Cinema[];
  experiences: ExperienceRecord[];
  featuredMovie: Movie;
}

export interface CinemaRepository {
  getHome(): Promise<HomePayload>;
  listMovies(filters?: MovieFilters): Promise<Movie[]>;
  getMovie(slug: string): Promise<Movie | null>;
  listCinemas(): Promise<Cinema[]>;
  getCinema(slug: string): Promise<Cinema | null>;
  listExperiences(): Promise<ExperienceRecord[]>;
  listScreenings(query?: ScreeningQuery): Promise<Screening[]>;
  getScreening(id: string): Promise<Screening | null>;
  getSeatMap(id: string): Promise<SeatMap | null>;
  findOrder(reference: string, email: string): Promise<Order | null>;
}

export interface FixtureData {
  meta: {
    schemaVersion: number;
    fixtureDate: string;
    timezone: string;
    currency: string;
    locale: string;
    noticeHe: string;
  };
  brand: Brand;
  home: {
    featuredMovieId: string;
    nowShowingMovieIds: string[];
    popularMovieIds: string[];
  };
  experiences: Array<Omit<ExperienceRecord, 'id' | 'imageUrl'> & { id: Exclude<Experience, 'standard'> }>;
  cinemas: Array<Omit<Cinema, 'imageUrl'> & { imageSourceUrl: string }>;
  movies: Array<Omit<Movie, 'posterUrl' | 'backdropUrl'> & { posterSourceUrl: string; backdropSourceUrl: string }>;
  seatMaps: SeatMapDefinition[];
  screenings: Screening[];
  orders: Order[];
}
