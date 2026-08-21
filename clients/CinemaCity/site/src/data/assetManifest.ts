import type { Cinema, ExperienceRecord, Movie } from './types';

export const brandAsset = '/images/brand/cinema-city-logo.png';

export const movieAssets: Record<string, Pick<Movie, 'posterUrl' | 'backdropUrl'>> = {
  'movie-spider-man-brand-new-day': {
    posterUrl: '/images/posters/spider-man-brand-new-day.jpg',
    backdropUrl: '/images/heroes/spider-man-brand-new-day.jpg',
  },
  'movie-spa-weekend': {
    posterUrl: '/images/posters/spa-weekend.jpg',
    backdropUrl: '/images/heroes/spa-weekend.jpg',
  },
  'movie-mutiny': {
    posterUrl: '/images/posters/mutiny.jpg',
    backdropUrl: '/images/heroes/mutiny.jpg',
  },
  'movie-coyote-vs-acme-he': {
    posterUrl: '/images/posters/coyote-vs-acme-he.jpg',
    backdropUrl: '/images/heroes/coyote-vs-acme-he.jpg',
  },
  'movie-insidious-out-of-the-further': {
    posterUrl: '/images/posters/insidious-out-of-the-further.jpg',
    backdropUrl: '/images/heroes/insidious-out-of-the-further.jpg',
  },
  'movie-la-la-land-10': {
    posterUrl: '/images/posters/la-la-land-10.jpg',
    backdropUrl: '/images/heroes/la-la-land-10.jpg',
  },
  'movie-pout-pout-fish-he': {
    posterUrl: '/images/posters/pout-pout-fish-he.jpg',
    backdropUrl: '/images/heroes/pout-pout-fish-he.jpg',
  },
  'movie-the-odyssey': {
    posterUrl: '/images/posters/the-odyssey.jpg',
    backdropUrl: '/images/heroes/the-odyssey.jpg',
  },
};

export const cinemaAssets: Record<string, Pick<Cinema, 'imageUrl'>> = {
  'cinema-glilot': { imageUrl: '/images/locations/glilot.jpg' },
  'cinema-rishon-lezion': { imageUrl: '/images/locations/rishon-lezion.jpg' },
  'cinema-jerusalem': { imageUrl: '/images/locations/jerusalem.jpg' },
  'cinema-kfar-saba': { imageUrl: '/images/locations/kfar-saba.jpg' },
  'cinema-netanya': { imageUrl: '/images/locations/netanya.jpg' },
  'cinema-hadera': { imageUrl: '/images/locations/hadera.jpg' },
  'cinema-beer-sheva': { imageUrl: '/images/locations/beer-sheva.jpg' },
  'cinema-ashdod': { imageUrl: '/images/locations/ashdod.jpg' },
};

export const experienceAssets: Record<string, Pick<ExperienceRecord, 'imageUrl'>> = {
  vip: { imageUrl: '/images/experiences/vip.jpg' },
  prime: { imageUrl: '/images/experiences/prime.jpg' },
  onyx: { imageUrl: '/images/experiences/onyx.jpg' },
};
