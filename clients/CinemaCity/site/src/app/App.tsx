import {
  Accessibility,
  BusFront,
  Check,
  ChevronLeft,
  CircleAlert,
  Clock3,
  Copy,
  Film,
  Info,
  MapPin,
  Menu,
  Minus,
  Navigation,
  ParkingCircle,
  Play,
  Plus,
  Search,
  Ticket,
  Trash2,
  Volume2,
  X,
} from 'lucide-react';
import { motion } from 'motion/react';
import {
  Link,
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router-dom';
import {
  createContext,
  type ButtonHTMLAttributes,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react';
import { trackEvent } from '../data/analytics';
import {
  calculateSubtotal,
  calculateTotal,
  cinemaRepository,
  experienceLabel,
  filterMovies,
  fixtureData,
  formatCurrency,
  formatDate,
  formatTime,
  getOpenStatus,
  isDraftExpired,
  toLocalDate,
  totalTickets,
  trimSeatsForTicketCount,
} from '../data/fixtureCinemaRepository';
import type {
  BookingDraft,
  Cinema,
  Experience,
  ExperienceRecord,
  HomePayload,
  Movie,
  MovieFilters,
  Order,
  Screening,
  SeatMap,
} from '../data/types';
import { brandAsset } from '../data/assetManifest';

const ACTIVE_CINEMA_KEY = 'cinemaCity.activeCinema.v1';
const BOOKING_DRAFT_KEY = 'cinemaCity.bookingDraft.v1';
const COOKIE_KEY = 'cinemaCity.cookieConsent.v1';
const CANCELLED_ORDERS_KEY = 'cinemaCity.cancelledOrders.v1';
const COMPLETED_ORDER_KEY = 'cinemaCity.completedOrder.v1';
const FIXTURE_DATE = fixtureData.meta.fixtureDate;

type DataState = {
  loading: boolean;
  error: string | null;
  home: HomePayload | null;
  movies: Movie[];
  cinemas: Cinema[];
  experiences: ExperienceRecord[];
  screenings: Screening[];
  seatMaps: Record<string, SeatMap>;
  reload: () => void;
};

type Toast = { id: number; message: string };

type ToastContextValue = {
  showToast: (message: string) => void;
};

type CinemaContextValue = {
  activeCinemaSlug: string;
  setActiveCinemaSlug: (slug: string) => void;
};

type BookingContextValue = {
  draft: BookingDraft;
  setDraft: (updater: BookingDraft | ((draft: BookingDraft) => BookingDraft)) => void;
  clearDraft: () => void;
};

const DataContext = createContext<DataState | null>(null);
const ToastContext = createContext<ToastContextValue | null>(null);
const CinemaContext = createContext<CinemaContextValue | null>(null);
const BookingContext = createContext<BookingContextValue | null>(null);

const emptyDraft: BookingDraft = {
  ticketQuantities: {},
  selectedSeatIds: [],
  discount: 0,
};

function readJson<T>(key: string, fallback: T): T {
  try {
    const value = window.localStorage.getItem(key);
    return value ? (JSON.parse(value) as T) : fallback;
  } catch {
    return fallback;
  }
}

function readSessionJson<T>(key: string, fallback: T): T {
  try {
    const value = window.sessionStorage.getItem(key);
    return value ? (JSON.parse(value) as T) : fallback;
  } catch {
    return fallback;
  }
}

function writeJson<T>(key: string, value: T) {
  window.localStorage.setItem(key, JSON.stringify(value));
}

function dateOptions(days = 7) {
  const base = new Date(`${FIXTURE_DATE}T12:00:00+03:00`);
  return Array.from({ length: days }, (_, index) => {
    const date = new Date(base);
    date.setDate(base.getDate() + index);
    return date.toISOString().slice(0, 10);
  });
}

function cn(...classes: Array<string | false | undefined>) {
  return classes.filter(Boolean).join(' ');
}

function groupBy<T>(items: T[], keyFn: (item: T) => string) {
  return items.reduce<Record<string, T[]>>((groups, item) => {
    const key = keyFn(item);
    groups[key] = groups[key] ?? [];
    groups[key].push(item);
    return groups;
  }, {});
}

function useData() {
  const context = useContext(DataContext);
  if (!context) throw new Error('useData must be used inside DataProvider');
  return context;
}

function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error('useToast must be used inside ToastProvider');
  return context;
}

function useCinema() {
  const context = useContext(CinemaContext);
  if (!context) throw new Error('useCinema must be used inside CinemaProvider');
  return context;
}

function useBooking() {
  const context = useContext(BookingContext);
  if (!context) throw new Error('useBooking must be used inside BookingProvider');
  return context;
}

function useDocumentTitle(title: string) {
  useEffect(() => {
    document.title = title;
  }, [title]);
}

function useScrollTopClass() {
  const location = useLocation();
  const [top, setTop] = useState(true);

  useEffect(() => {
    const update = () => setTop(window.scrollY < 40);
    update();
    window.addEventListener('scroll', update, { passive: true });
    return () => window.removeEventListener('scroll', update);
  }, []);

  return location.pathname === '/' && top;
}

function DataProvider({ children }: { children: ReactNode }) {
  const [version, setVersion] = useState(0);
  const [state, setState] = useState<DataState>({
    loading: true,
    error: null,
    home: null,
    movies: [],
    cinemas: [],
    experiences: [],
    screenings: [],
    seatMaps: {},
    reload: () => setVersion((current) => current + 1),
  });

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setState((current) => ({ ...current, loading: true, error: null }));
      try {
        const [home, screenings, seatMaps] = await Promise.all([
          cinemaRepository.getHome(),
          cinemaRepository.listScreenings(),
          Promise.all(fixtureData.seatMaps.map((seatMap) => cinemaRepository.getSeatMap(seatMap.id))),
        ]);
        if (cancelled) return;
        setState({
          loading: false,
          error: null,
          home,
          movies: home.movies,
          cinemas: home.cinemas,
          experiences: home.experiences,
          screenings,
          seatMaps: Object.fromEntries(seatMaps.filter(Boolean).map((seatMap) => [seatMap!.id, seatMap!])),
          reload: () => setVersion((current) => current + 1),
        });
      } catch (error) {
        if (cancelled) return;
        setState((current) => ({
          ...current,
          loading: false,
          error: error instanceof Error ? error.message : 'Repository failed',
        }));
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [version]);

  return <DataContext.Provider value={state}>{children}</DataContext.Provider>;
}

function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  function showToast(message: string) {
    const toast = { id: Date.now(), message };
    setToasts((current) => [...current, toast]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((item) => item.id !== toast.id));
    }, 3600);
  }

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div className="toast-region" aria-live="polite" aria-atomic="true">
        {toasts.map((toast) => (
          <div className="toast" key={toast.id}>
            {toast.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function CinemaProvider({ children }: { children: ReactNode }) {
  const [activeCinemaSlug, setStoredCinemaSlug] = useState(() => readJson(ACTIVE_CINEMA_KEY, 'glilot'));

  function setActiveCinemaSlug(slug: string) {
    setStoredCinemaSlug(slug);
    writeJson(ACTIVE_CINEMA_KEY, slug);
    trackEvent('cinema_selected', { slug });
  }

  return (
    <CinemaContext.Provider value={{ activeCinemaSlug, setActiveCinemaSlug }}>{children}</CinemaContext.Provider>
  );
}

function BookingProvider({ children }: { children: ReactNode }) {
  const [draft, setDraftState] = useState<BookingDraft>(() => readJson(BOOKING_DRAFT_KEY, emptyDraft));

  function setDraft(updater: BookingDraft | ((draft: BookingDraft) => BookingDraft)) {
    setDraftState((current) => {
      const next = typeof updater === 'function' ? updater(current) : updater;
      writeJson(BOOKING_DRAFT_KEY, next);
      return next;
    });
  }

  function clearDraft() {
    setDraftState(emptyDraft);
    window.localStorage.removeItem(BOOKING_DRAFT_KEY);
  }

  return <BookingContext.Provider value={{ draft, setDraft, clearDraft }}>{children}</BookingContext.Provider>;
}

function Button({
  children,
  variant = 'secondary',
  type = 'button',
  className,
  ...props
}: {
  children: ReactNode;
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  type?: 'button' | 'submit';
  className?: string;
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button type={type} className={cn('button', variant, className)} {...props}>
      {children}
    </button>
  );
}

function IconButton({
  label,
  children,
  className,
  ...props
}: {
  label: string;
  children: ReactNode;
  className?: string;
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button type="button" className={cn('icon-button', className)} aria-label={label} {...props}>
      {children}
    </button>
  );
}

function Field({
  label,
  children,
  error,
}: {
  label: string;
  children: ReactNode;
  error?: string;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      <span className="field-error" role={error ? 'alert' : undefined}>
        {error ?? ''}
      </span>
    </label>
  );
}

function StatusBadge({ children, tone = 'gold' }: { children: ReactNode; tone?: 'gold' | 'teal' | 'sky' | 'red' | 'success' }) {
  return <span className={cn('badge', tone !== 'gold' && tone)}>{children}</span>;
}

function Modal({
  title,
  children,
  onClose,
  labelledBy,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  labelledBy: string;
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const focusable = panelRef.current?.querySelector<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    focusable?.focus();

    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') onClose();
      if (event.key !== 'Tab') return;
      const items = Array.from(
        panelRef.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      );
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [onClose]);

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="dialog-panel" role="dialog" aria-modal="true" aria-labelledby={labelledBy} ref={panelRef}>
        <div className="dialog-header">
          <h2 id={labelledBy}>{title}</h2>
          <IconButton label="סגירה" onClick={onClose}>
            <X aria-hidden="true" />
          </IconButton>
        </div>
        {children}
      </div>
    </div>
  );
}

function AppProviders({ children }: { children: ReactNode }) {
  return (
    <DataProvider>
      <ToastProvider>
        <CinemaProvider>
          <BookingProvider>{children}</BookingProvider>
        </CinemaProvider>
      </ToastProvider>
    </DataProvider>
  );
}

export function App() {
  return (
    <AppProviders>
      <Shell />
    </AppProviders>
  );
}

function Shell() {
  const { loading, error, reload } = useData();
  const location = useLocation();
  const mainRef = useRef<HTMLElement>(null);
  const [searchOpen, setSearchOpen] = useState(false);

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'instant' });
    window.setTimeout(() => {
      const h1 = document.querySelector<HTMLElement>('main h1');
      (h1 ?? mainRef.current)?.focus();
    }, 0);
  }, [location.pathname]);

  return (
    <div className="app">
      <a className="skip-link" href="#main-content">
        דלגו לתוכן הראשי
      </a>
      <Header onSearch={() => setSearchOpen(true)} />
      <OfflineBanner />
      <main id="main-content" className="main" tabIndex={-1} ref={mainRef}>
        {error ? (
          <ErrorState onRetry={reload} />
        ) : loading ? (
          <LoadingShell />
        ) : (
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/movies" element={<MoviesPage />} />
            <Route path="/movies/:movieSlug" element={<MovieDetailPage />} />
            <Route path="/cinemas" element={<CinemasPage />} />
            <Route path="/cinemas/:cinemaSlug" element={<CinemaDetailPage />} />
            <Route path="/experiences" element={<ExperiencesPage />} />
            <Route path="/booking" element={<BookingScreeningPage />} />
            <Route path="/booking/seats" element={<BookingSeatsPage />} />
            <Route path="/booking/checkout" element={<BookingCheckoutPage />} />
            <Route path="/booking/confirmation" element={<BookingConfirmationPage />} />
            <Route path="/manage-order" element={<ManageOrderPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        )}
      </main>
      <Footer />
      <CookieBanner />
      {searchOpen && <SearchDialog onClose={() => setSearchOpen(false)} />}
    </div>
  );
}

function Header({ onSearch }: { onSearch: () => void }) {
  const isHomeTop = useScrollTopClass();
  const { cinemas } = useData();
  const { activeCinemaSlug, setActiveCinemaSlug } = useCinema();
  const [mobileOpen, setMobileOpen] = useState(false);
  const activeCinema = cinemas.find((cinema) => cinema.slug === activeCinemaSlug) ?? cinemas[0];

  return (
    <header className={cn('site-header', isHomeTop && 'home-top')}>
      <div className="header-inner">
        <Link className="brand-logo" to="/" aria-label="סינמה סיטי עמוד הבית">
          <img src={brandAsset} width="104" height="72" alt="סינמה סיטי" />
        </Link>
        <nav className="nav" aria-label="ניווט ראשי">
          <NavLink to="/movies">סרטים</NavLink>
          <NavLink to="/cinemas">מתחמים</NavLink>
          <NavLink to="/experiences">VIP וחוויות</NavLink>
          <NavLink to="/movies?audience=children">ילדים</NavLink>
        </nav>
        <div className="header-spacer" />
        <div className="header-actions">
          <label className="field" style={{ width: 190 }}>
            <span>
              <MapPin size={15} aria-hidden="true" /> מתחם פעיל
            </span>
            <select value={activeCinema?.slug ?? 'glilot'} onChange={(event) => setActiveCinemaSlug(event.target.value)}>
              {cinemas.map((cinema) => (
                <option key={cinema.id} value={cinema.slug}>
                  {cinema.cityHe}
                </option>
              ))}
            </select>
          </label>
          <IconButton label="חיפוש באתר" onClick={onSearch}>
            <Search aria-hidden="true" />
          </IconButton>
          <Link to="/manage-order" className="button ghost">
            ניהול הזמנה
          </Link>
          <Link to="/booking" className="button primary">
            <Ticket size={18} aria-hidden="true" />
            להזמנת כרטיסים
          </Link>
        </div>
      </div>
      <div className="mobile-header">
        <IconButton label="פתיחת תפריט" onClick={() => setMobileOpen(true)}>
          <Menu aria-hidden="true" />
        </IconButton>
        <Link className="brand-logo" to="/" aria-label="סינמה סיטי עמוד הבית">
          <img src={brandAsset} width="76" height="52" alt="סינמה סיטי" />
        </Link>
        <Link to="/booking" className="icon-button" aria-label="להזמנת כרטיסים">
          <Ticket aria-hidden="true" />
        </Link>
      </div>
      <div className={cn('mobile-drawer', mobileOpen && 'open')} aria-hidden={!mobileOpen}>
        <div className="mobile-drawer-panel" role="dialog" aria-modal="true" aria-labelledby="mobile-menu-title">
          <div className="dialog-header">
            <h2 id="mobile-menu-title">תפריט</h2>
            <IconButton label="סגירת תפריט" onClick={() => setMobileOpen(false)}>
              <X aria-hidden="true" />
            </IconButton>
          </div>
          <nav className="nav" aria-label="ניווט נייד">
            <NavLink to="/movies" onClick={() => setMobileOpen(false)}>
              סרטים
            </NavLink>
            <NavLink to="/cinemas" onClick={() => setMobileOpen(false)}>
              מתחמים
            </NavLink>
            <NavLink to="/experiences" onClick={() => setMobileOpen(false)}>
              VIP וחוויות
            </NavLink>
            <NavLink to="/movies?audience=children" onClick={() => setMobileOpen(false)}>
              ילדים
            </NavLink>
            <NavLink to="/manage-order" onClick={() => setMobileOpen(false)}>
              ניהול הזמנה
            </NavLink>
          </nav>
          <Field label="מתחם פעיל">
            <select value={activeCinema?.slug ?? 'glilot'} onChange={(event) => setActiveCinemaSlug(event.target.value)}>
              {cinemas.map((cinema) => (
                <option key={cinema.id} value={cinema.slug}>
                  {cinema.nameHe}
                </option>
              ))}
            </select>
          </Field>
          <Button variant="secondary" onClick={onSearch}>
            <Search size={18} aria-hidden="true" />
            חיפוש
          </Button>
        </div>
        <button className="drawer-scrim" type="button" aria-label="סגירת תפריט" onClick={() => setMobileOpen(false)} />
      </div>
    </header>
  );
}

function OfflineBanner() {
  const [online, setOnline] = useState(() => navigator.onLine);
  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener('online', update);
    window.addEventListener('offline', update);
    return () => {
      window.removeEventListener('online', update);
      window.removeEventListener('offline', update);
    };
  }, []);
  if (online) return null;
  return (
    <div className="alert" role="status">
      <CircleAlert aria-hidden="true" />
      אין כרגע חיבור לרשת. אפשר להמשיך לעיין במידע שכבר נטען.
    </div>
  );
}

function LoadingShell() {
  return (
    <section className="section">
      <div className="section-inner empty-state" aria-busy="true">
        <Film size={40} aria-hidden="true" />
        <h1 tabIndex={-1}>טוענים הקרנות</h1>
        <p className="muted">מכינים את לוח הסרטים המקומי.</p>
      </div>
    </section>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  useDocumentTitle('משהו השתבש | סינמה סיטי');
  return (
    <section className="section">
      <div className="section-inner empty-state">
        <CircleAlert size={42} aria-hidden="true" />
        <h1 tabIndex={-1}>משהו השתבש בהקרנת העמוד</h1>
        <p className="muted">לא הצלחנו לטעון את המידע. נסו שוב.</p>
        <Button variant="primary" onClick={onRetry}>
          ניסיון נוסף
        </Button>
      </div>
    </section>
  );
}

function Footer() {
  const { showToast } = useToast();
  const [email, setEmail] = useState('');
  const [consent, setConsent] = useState(false);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!email.includes('@') || !consent) {
      showToast('כדי להירשם צריך כתובת מייל תקינה ואישור קבלת עדכונים.');
      return;
    }
    setEmail('');
    setConsent(false);
    showToast('נרשמתם לעדכונים בגרסת ההדגמה.');
  }

  return (
    <footer className="site-footer">
      <div className="footer-inner">
        <div className="footer-grid">
          <div className="footer-column">
            <img src={brandAsset} width="104" height="72" alt="סינמה סיטי" style={{ objectFit: 'contain' }} />
            <p>עיר הסרטים של ישראל</p>
            <p className="muted">קונספט עיצובי להזמנת כרטיסים וחיפוש הקרנות.</p>
          </div>
          <FooterColumn title="גילוי" links={[['סרטים', '/movies'], ['מתחמים', '/cinemas'], ['VIP וחוויות', '/experiences'], ['ילדים', '/movies?audience=children']]} />
          <FooterColumn title="שירות" links={[['ניהול הזמנה', '/manage-order'], ['צור קשר', '/'], ['שאלות נפוצות', '/'], ['נגישות', '/']]} />
          <FooterColumn title="משפטי" links={[['תנאי שימוש', '/'], ['פרטיות', '/'], ['מדיניות מצלמות', '/'], ['הצהרת נגישות', '/']]} />
        </div>
        <form className="newsletter-row" onSubmit={submit}>
          <Field label="עדכוני סרטים והטבות">
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="name@example.com"
              dir="ltr"
            />
          </Field>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
            אני מאשר/ת קבלת עדכונים
          </label>
          <Button type="submit" variant="primary">
            הרשמה
          </Button>
        </form>
        <p className="bottom-line">© 2026 ניו לינאו סינמה (2006) בע״מ. קונספט עיצובי לצורכי הדגמה.</p>
      </div>
    </footer>
  );
}

function FooterColumn({ title, links }: { title: string; links: Array<[string, string]> }) {
  return (
    <div className="footer-column">
      <h3>{title}</h3>
      {links.map(([label, href]) => (
        <Link key={label} to={href} className="muted">
          {label}
        </Link>
      ))}
    </div>
  );
}

function CookieBanner() {
  const { showToast } = useToast();
  const [visible, setVisible] = useState(() => !window.localStorage.getItem(COOKIE_KEY));

  function choose(value: 'all' | 'essential') {
    window.localStorage.setItem(COOKIE_KEY, value);
    setVisible(false);
    trackEvent('cookie_consent_updated', { value });
    showToast(value === 'all' ? 'אושרו כל העוגיות.' : 'נשמרו עוגיות חיוניות בלבד.');
  }

  if (!visible) return null;
  return (
    <aside className="cookie-banner" aria-label="הודעת עוגיות">
      <div className="section-inner cookie-inner">
        <div>
          <h2>עוגיות, בלי דרמה</h2>
          <p className="muted">
            אנחנו משתמשים בעוגיות כדי לשפר את חוויית הגלישה, למדוד שימוש ולהתאים תוכן. תוכלו לאשר הכול או להמשיך עם עוגיות
            חיוניות בלבד.
          </p>
        </div>
        <div className="cookie-actions">
          <Button variant="primary" onClick={() => choose('all')}>
            אישור הכול
          </Button>
          <Button variant="secondary" onClick={() => choose('essential')}>
            חיוניות בלבד
          </Button>
          <Link to="/" className="button ghost">
            מדיניות פרטיות
          </Link>
        </div>
      </div>
    </aside>
  );
}

function SearchDialog({ onClose }: { onClose: () => void }) {
  const { movies, cinemas } = useData();
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const trimmed = query.trim().toLowerCase();
  const movieResults =
    trimmed.length >= 2
      ? movies
          .filter(
            (movie) =>
              movie.titleHe.toLowerCase().includes(trimmed) ||
              movie.titleOriginal.toLowerCase().includes(trimmed) ||
              movie.genres.some((genre) => genre.toLowerCase().includes(trimmed)),
          )
          .slice(0, 5)
      : [];
  const cinemaResults =
    trimmed.length >= 2
      ? cinemas.filter((cinema) => cinema.cityHe.toLowerCase().includes(trimmed) || cinema.nameHe.toLowerCase().includes(trimmed)).slice(0, 3)
      : [];
  const results = [
    ...movieResults.map((movie) => ({ type: 'movie' as const, label: movie.titleHe, sub: movie.titleOriginal, href: `/movies/${movie.slug}` })),
    ...cinemaResults.map((cinema) => ({ type: 'cinema' as const, label: cinema.nameHe, sub: cinema.addressHe, href: `/cinemas/${cinema.slug}` })),
  ];

  function openResult(href: string) {
    const item = results.find((result) => result.href === href);
    trackEvent('search_result_selected', { type: item?.type, href });
    onClose();
    navigate(href);
  }

  function handleKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActiveIndex((current) => Math.min(results.length - 1, current + 1));
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveIndex((current) => Math.max(0, current - 1));
    }
    if (event.key === 'Enter' && results[activeIndex]) {
      event.preventDefault();
      openResult(results[activeIndex].href);
    }
  }

  useEffect(() => {
    trackEvent('search_opened');
  }, []);

  return (
    <Modal title="חיפוש באתר" labelledBy="search-title" onClose={onClose}>
      <Field label="חיפוש באתר">
        <input
          autoFocus
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setActiveIndex(0);
          }}
          onKeyDown={handleKey}
          placeholder="חפשו סרט או מתחם"
          aria-controls="search-results"
        />
      </Field>
      {trimmed.length < 2 ? (
        <div className="search-results">
          <p className="label">חיפושים מהירים</p>
          {[
            ['סרטי ילדים', '/movies?audience=children'],
            ['VIP', '/movies?experience=vip'],
            ['הקרנות הערב', '/booking'],
            ['סינמה סיטי גלילות', '/cinemas/glilot'],
          ].map(([label, href]) => (
            <button key={href} type="button" className="search-result" onClick={() => openResult(href)}>
              <span>{label}</span>
              <ChevronLeft aria-hidden="true" />
            </button>
          ))}
        </div>
      ) : results.length ? (
        <div className="search-results" id="search-results">
          {results.map((result, index) => (
            <button
              type="button"
              key={result.href}
              className={cn('search-result', index === activeIndex && 'active')}
              onMouseEnter={() => setActiveIndex(index)}
              onClick={() => openResult(result.href)}
            >
              <span>
                <strong>{result.label}</strong>
                <br />
                <span className="muted">{result.sub}</span>
              </span>
              <ChevronLeft aria-hidden="true" />
            </button>
          ))}
        </div>
      ) : (
        <p className="muted" style={{ marginBlockStart: 16 }}>
          לא מצאנו תוצאה ל״{query}״
        </p>
      )}
    </Modal>
  );
}

function HomePage() {
  const { home, movies, cinemas, experiences, screenings } = useData();
  const { activeCinemaSlug, setActiveCinemaSlug } = useCinema();
  const [tab, setTab] = useState<'all' | 'children' | 'vip' | 'coming'>('all');
  const [activeLocation, setActiveLocation] = useState(activeCinemaSlug);
  const [date, setDate] = useState(FIXTURE_DATE);
  const [trailerOpen, setTrailerOpen] = useState(false);
  useDocumentTitle('סינמה סיטי | סרטים, הקרנות והזמנת כרטיסים');

  const activeCinema = cinemas.find((cinema) => cinema.slug === activeCinemaSlug) ?? cinemas[0];
  const featuredMovie = home?.featuredMovie ?? movies[0];
  const visibleMovies = movies
    .filter((movie) => {
      if (tab === 'children') return movie.audience === 'children';
      if (tab === 'vip') return screenings.some((screening) => screening.movieId === movie.id && screening.experience === 'vip');
      if (tab === 'coming') return movie.status === 'coming-soon';
      return true;
    })
    .slice(0, 6);
  const location = cinemas.find((cinema) => cinema.slug === activeLocation) ?? activeCinema;

  return (
    <>
      <section className="hero" aria-labelledby="home-hero-title">
        <div className="hero-image">
          <img src={featuredMovie.backdropUrl} alt="" width="1920" height="799" />
        </div>
        <div className="section-inner hero-content">
          <motion.div
            className="hero-copy"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.42 }}
          >
            <p className="eyebrow">הסרט הגדול של השבוע</p>
            <h1 id="home-hero-title" tabIndex={-1}>
              ספיידרמן: יום חדש
            </h1>
            <p className="muted ltr">SPIDER-MAN: BRAND NEW DAY</p>
            <p>פנטזיה • 150 דקות • מותר לכל</p>
            <div className="hero-actions">
              <Button variant="secondary" onClick={() => setTrailerOpen(true)}>
                <Play size={18} aria-hidden="true" />
                לצפייה בטריילר
              </Button>
              <Link to={`/movies/${featuredMovie.slug}`} className="button ghost">
                לפרטי הסרט
              </Link>
            </div>
          </motion.div>
        </div>
        <div className="hero-indicators" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <BookingRail />
      </section>

      <section className="section" id="now-showing">
        <div className="section-inner">
          <div className="section-heading">
            <h2>עכשיו בקולנוע</h2>
            <div className="chip-row" role="tablist" aria-label="סינון סרטים">
              {[
                ['all', 'הכול'],
                ['children', 'ילדים'],
                ['vip', 'VIP'],
                ['coming', 'בקרוב'],
              ].map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  className={cn('chip', tab === value && 'selected')}
                  onClick={() => setTab(value as typeof tab)}
                >
                  {label}
                </button>
              ))}
              <Link to="/movies" className="button ghost">
                לכל הסרטים
              </Link>
            </div>
          </div>
          <div className="poster-grid">
            {visibleMovies.map((movie, index) => (
              <motion.div
                key={movie.id}
                initial={{ opacity: 0, y: 8 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: index * 0.045 }}
              >
                <MoviePosterCard movie={movie} activeCinemaSlug={activeCinemaSlug} />
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      <section className="section band">
        <div className="section-inner">
          <div className="section-heading">
            <h2>הערב לפי שעה</h2>
            <div className="chip-row">
              <label className="field" style={{ minWidth: 190 }}>
                <span>מתחם</span>
                <select value={activeCinemaSlug} onChange={(event) => setActiveCinemaSlug(event.target.value)}>
                  {cinemas.map((cinema) => (
                    <option key={cinema.id} value={cinema.slug}>
                      {cinema.cityHe}
                    </option>
                  ))}
                </select>
              </label>
              {dateOptions(5).map((option) => (
                <button key={option} type="button" className={cn('chip', date === option && 'selected')} onClick={() => setDate(option)}>
                  {formatDate(option)}
                </button>
              ))}
            </div>
          </div>
          <TimeBuckets screenings={screenings.filter((screening) => screening.cinemaId === activeCinema.id && toLocalDate(screening.startsAt) === date)} />
        </div>
      </section>

      <section className="section">
        <div className="section-inner">
          <div className="section-heading">
            <h2>יותר מסרט</h2>
            <Link to="/experiences" className="button ghost">
              לכל החוויות
            </Link>
          </div>
          <div className="experience-band">
            {experiences.map((experience) => (
              <ExperienceLink key={experience.id} experience={experience} />
            ))}
          </div>
        </div>
      </section>

      <section className="section band">
        <div className="section-inner">
          <div className="section-heading">
            <h2>המתחם שלכם</h2>
            <p className="muted">עברו בין המתחמים כדי לראות תמונה, חוויות וכתובת.</p>
          </div>
          <div className="locations-split">
            <div className="location-list">
              {[...cinemas].sort((a) => (a.slug === activeCinemaSlug ? -1 : 0)).map((cinema) => (
                <Link
                  key={cinema.id}
                  to={`/cinemas/${cinema.slug}`}
                  className={cn('location-row', location?.slug === cinema.slug && 'active')}
                  onMouseEnter={() => setActiveLocation(cinema.slug)}
                  onFocus={() => setActiveLocation(cinema.slug)}
                >
                  <strong>{cinema.nameHe}</strong>
                  <span className="muted">{cinema.addressHe}</span>
                  <span className="chip-row">
                    {cinema.experiences.map((experience) => (
                      <StatusBadge key={experience} tone={experience === 'standard' ? 'gold' : experience === 'vip' ? 'red' : experience === 'prime' ? 'teal' : 'sky'}>
                        {experienceLabel(experience)}
                      </StatusBadge>
                    ))}
                  </span>
                </Link>
              ))}
            </div>
            {location && (
              <div>
                <div className="location-image">
                  <img src={location.imageUrl} width="640" height="440" alt={location.nameHe} loading="lazy" />
                </div>
                <p className="muted" style={{ marginBlockStart: 12 }}>
                  {location.descriptionHe}
                </p>
              </div>
            )}
          </div>
        </div>
      </section>

      <ServiceStrip />
      {trailerOpen && featuredMovie && <TrailerDialog movie={featuredMovie} onClose={() => setTrailerOpen(false)} />}
    </>
  );
}

function BookingRail() {
  const { movies, cinemas } = useData();
  const { activeCinemaSlug } = useCinema();
  const navigate = useNavigate();
  const [mode, setMode] = useState<'movie' | 'cinema'>('movie');
  const [movieSlug, setMovieSlug] = useState('spider-man-brand-new-day');
  const [cinemaSlug, setCinemaSlug] = useState(activeCinemaSlug);
  const [date, setDate] = useState(FIXTURE_DATE);
  const [experience, setExperience] = useState<Experience | 'all'>('all');

  useEffect(() => {
    setCinemaSlug(activeCinemaSlug);
  }, [activeCinemaSlug]);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!movieSlug || !cinemaSlug) return;
    const params = new URLSearchParams({
      movie: movieSlug,
      cinema: cinemaSlug,
      date,
      experience,
    });
    navigate(`/booking?${params.toString()}`);
  }

  const movieField = (
    <Field label="סרט">
      <select value={movieSlug} onChange={(event) => setMovieSlug(event.target.value)}>
        <option value="">בחרו סרט</option>
        {movies.map((movie) => (
          <option key={movie.id} value={movie.slug}>
            {movie.titleHe}
          </option>
        ))}
      </select>
    </Field>
  );
  const cinemaField = (
    <Field label="מתחם">
      <select value={cinemaSlug} onChange={(event) => setCinemaSlug(event.target.value)}>
        <option value="">בחרו מתחם</option>
        {cinemas.map((cinema) => (
          <option key={cinema.id} value={cinema.slug}>
            {cinema.cityHe}
          </option>
        ))}
      </select>
    </Field>
  );

  return (
    <form className="booking-rail" onSubmit={submit} aria-label="חיפוש הקרנות מהיר">
      <div className="section-inner booking-rail-inner">
        <div className="segmented" aria-label="מצב הזמנה">
          <button type="button" className={mode === 'movie' ? 'active' : ''} onClick={() => setMode('movie')}>
            לפי סרט
          </button>
          <button type="button" className={mode === 'cinema' ? 'active' : ''} onClick={() => setMode('cinema')}>
            לפי מתחם
          </button>
        </div>
        {mode === 'movie' ? (
          <>
            {movieField}
            {cinemaField}
          </>
        ) : (
          <>
            {cinemaField}
            {movieField}
          </>
        )}
        <Field label="תאריך">
          <select value={date} onChange={(event) => setDate(event.target.value)}>
            {dateOptions(7).map((option) => (
              <option key={option} value={option}>
                {formatDate(option)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="פורמט">
          <select value={experience} onChange={(event) => setExperience(event.target.value as Experience | 'all')}>
            <option value="all">כל הפורמטים</option>
            <option value="standard">רגיל</option>
            <option value="vip">VIP</option>
            <option value="prime">PRIME</option>
            <option value="onyx">ONYX</option>
          </select>
        </Field>
        <Button type="submit" variant="primary" disabled={!movieSlug || !cinemaSlug}>
          {movieSlug && cinemaSlug ? 'הציגו שעות' : 'בחרו סרט ומתחם'}
        </Button>
      </div>
    </form>
  );
}

function MoviePosterCard({ movie, activeCinemaSlug }: { movie: Movie; activeCinemaSlug: string }) {
  const { screenings, cinemas } = useData();
  const navigate = useNavigate();
  const activeCinema = cinemas.find((cinema) => cinema.slug === activeCinemaSlug);
  const movieScreenings = screenings
    .filter((screening) => screening.movieId === movie.id && (!activeCinema || screening.cinemaId === activeCinema.id))
    .slice(0, 2);

  function openScreening(screening: Screening) {
    trackEvent('showtime_selected', { screeningId: screening.id, context: 'poster-card' });
    navigate(`/booking?screening=${screening.id}`);
  }

  return (
    <article className="poster-card">
      <div className="poster-frame">
        <Link to={`/movies/${movie.slug}`} aria-label={`${movie.titleHe}, לפרטים`}>
          <img src={movie.posterUrl} width="236" height="350" alt={`פוסטר הסרט ${movie.titleHe}`} loading="lazy" />
        </Link>
        {movie.badges[0] && <span className="badge" style={{ position: 'absolute', insetBlockStart: 8, insetInlineEnd: 8 }}>{movie.badges[0]}</span>}
        <div className="poster-actions">
          <Link to={`/movies/${movie.slug}`} className="button ghost">
            לפרטים
          </Link>
          <IconButton label={`הזמנת כרטיסים ל${movie.titleHe}`} onClick={() => movieScreenings[0] && openScreening(movieScreenings[0])}>
            <Ticket aria-hidden="true" />
          </IconButton>
        </div>
      </div>
      <Link to={`/movies/${movie.slug}`} className="movie-title" title={movie.titleHe}>
        {movie.titleHe}
      </Link>
      <p className="metadata">{movie.genres.join(' / ')} • {movie.runtimeMinutes} דקות</p>
      <div className="showtime-row">
        {movieScreenings.length ? (
          movieScreenings.map((screening) => <ShowtimeChip key={screening.id} screening={screening} onClick={() => openScreening(screening)} />)
        ) : (
          <span className="metadata">אין הקרנות במתחם הפעיל</span>
        )}
      </div>
    </article>
  );
}

function ShowtimeChip({
  screening,
  selected,
  onClick,
}: {
  screening: Screening;
  selected?: boolean;
  onClick: () => void;
}) {
  const soldOut = screening.availability === 'sold-out';
  return (
    <button
      type="button"
      className={cn('chip', selected && 'selected', soldOut && 'sold')}
      disabled={soldOut}
      onClick={onClick}
      aria-label={`${formatTime(screening.startsAt)}, ${experienceLabel(screening.experience)}${soldOut ? ', אזל' : ''}`}
    >
      <span className="ltr">{formatTime(screening.startsAt)}</span>
    </button>
  );
}

function TimeBuckets({ screenings }: { screenings: Screening[] }) {
  const { movies } = useData();
  const navigate = useNavigate();
  const buckets = [
    { label: 'עד 18:00', predicate: (hour: number) => hour < 18 },
    { label: '18:00-21:00', predicate: (hour: number) => hour >= 18 && hour < 21 },
    { label: 'אחרי 21:00', predicate: (hour: number) => hour >= 21 },
  ];

  if (!screenings.length) {
    return <EmptyState title="אין הקרנות בתאריך הזה" body="נסו לבחור תאריך אחר או מתחם אחר." />;
  }

  return (
    <div className="showtime-tool">
      {buckets.map((bucket) => {
        const items = screenings.filter((screening) => bucket.predicate(new Date(screening.startsAt).getHours()));
        if (!items.length) return null;
        return (
          <div key={bucket.label} className="tool-panel">
            <h3>{bucket.label}</h3>
            <div className="showtime-tool" style={{ marginBlockStart: 16 }}>
              {Object.entries(groupBy(items, (screening) => screening.movieId))
                .slice(0, 5)
                .map(([movieId, group]) => {
                  const movie = movies.find((item) => item.id === movieId);
                  if (!movie || !group) return null;
                  return (
                    <div className="screening-row" key={movieId}>
                      <div>
                        <strong>{movie.titleHe}</strong>
                        <p className="metadata">
                          {group[0].spokenLanguage} • {experienceLabel(group[0].experience)} • {movie.runtimeMinutes} דקות
                        </p>
                      </div>
                      <div className="chip-row">
                        {group.map((screening) => (
                          <ShowtimeChip key={screening.id} screening={screening} onClick={() => navigate(`/booking?screening=${screening.id}`)} />
                        ))}
                      </div>
                    </div>
                  );
                })}
            </div>
          </div>
        );
      })}
      <Link to="/booking" className="button ghost">
        לכל ההקרנות
      </Link>
    </div>
  );
}

function ExperienceLink({ experience }: { experience: ExperienceRecord }) {
  const tone = experience.accent === 'gold' ? 'gold' : experience.accent === 'teal' ? 'teal' : 'sky';
  return (
    <Link to={`/experiences#${experience.id}`} className="experience-link">
      <div className="experience-image">
        <img src={experience.imageUrl} width="420" height="260" alt={experience.nameHe} loading="lazy" />
      </div>
      <div className="experience-copy">
        <StatusBadge tone={tone}>{experience.nameHe}</StatusBadge>
        <h3>{experience.headingHe}</h3>
        <p className="muted">{experience.descriptionHe.slice(0, 92)}...</p>
        <span className="button ghost">
          לפרטים <ChevronLeft size={18} aria-hidden="true" />
        </span>
      </div>
    </Link>
  );
}

function ServiceStrip() {
  return (
    <section className="section">
      <div className="section-inner service-strip">
        <Link to="/manage-order" className="service-item">
          <Ticket aria-hidden="true" /> בדיקה או ביטול הזמנה
        </Link>
        <Link to="/" className="service-item">
          <Accessibility aria-hidden="true" /> נגישות
        </Link>
        <Link to="/" className="service-item">
          <Info aria-hidden="true" /> שאלות נפוצות
        </Link>
        <Link to="/" className="service-item">
          <MapPin aria-hidden="true" /> צור קשר
        </Link>
      </div>
    </section>
  );
}

function MoviesPage() {
  const { movies, screenings } = useData();
  const [params, setParams] = useSearchParams();
  const filters: MovieFilters = {
    query: params.get('q') ?? '',
    status: (params.get('status') as MovieFilters['status']) ?? 'now-showing',
    genre: params.get('genre') ?? '',
    language: params.get('language') ?? '',
    experience: (params.get('experience') as MovieFilters['experience']) ?? 'all',
    audience: params.get('audience') === 'children' ? 'children' : 'all',
    sort: (params.get('sort') as MovieFilters['sort']) ?? 'soonest',
  };
  const results = filterMovies(movies, screenings, filters);
  const genres = [...new Set(movies.flatMap((movie) => movie.genres))].sort((a, b) => a.localeCompare(b, 'he'));
  const [childrenChecked, setChildrenChecked] = useState(filters.audience === 'children');
  useDocumentTitle('סרטים עכשיו בקולנוע | סינמה סיטי');

  useEffect(() => {
    setChildrenChecked(filters.audience === 'children');
  }, [filters.audience]);

  function setParam(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (!value || value === 'all' || (key === 'status' && value === 'now-showing')) next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
    trackEvent('movie_filter_changed', { key, value });
  }

  function clearFilters() {
    setParams({}, { replace: true });
  }

  const changed = params.toString().length > 0;

  return (
    <>
      <section className="page-title-band">
        <div className="section-inner">
          <h1 tabIndex={-1}>סרטים בסינמה סיטי</h1>
          <p>בחרו סרט, מתחם ושעה שמתאימים לכם.</p>
        </div>
      </section>
      <section className="sticky-filter">
        <div className="section-inner filter-grid">
          <Field label="חיפוש סרט">
            <input value={filters.query} onChange={(event) => setParam('q', event.target.value)} />
          </Field>
          <Field label="סטטוס">
            <select value={filters.status} onChange={(event) => setParam('status', event.target.value)}>
              <option value="now-showing">עכשיו</option>
              <option value="coming-soon">בקרוב</option>
              <option value="all">הכול</option>
            </select>
          </Field>
          <Field label="ז׳אנר">
            <select value={filters.genre} onChange={(event) => setParam('genre', event.target.value)}>
              <option value="">כל הז׳אנרים</option>
              {genres.map((genre) => (
                <option key={genre} value={genre}>
                  {genre}
                </option>
              ))}
            </select>
          </Field>
          <Field label="שפה">
            <select value={filters.language} onChange={(event) => setParam('language', event.target.value)}>
              <option value="">כל השפות</option>
              {['עברית', 'אנגלית', 'רוסית', 'צרפתית'].map((language) => (
                <option key={language} value={language}>
                  {language}
                </option>
              ))}
            </select>
          </Field>
          <Field label="חוויה">
            <select value={filters.experience} onChange={(event) => setParam('experience', event.target.value)}>
              <option value="all">כל החוויות</option>
              <option value="standard">רגיל</option>
              <option value="vip">VIP</option>
              <option value="prime">PRIME</option>
              <option value="onyx">ONYX</option>
            </select>
          </Field>
          <div className="field">
            <label style={{ display: 'flex', gap: 8, alignItems: 'center', minHeight: 48 }}>
              <input
                type="checkbox"
                checked={childrenChecked}
                onChange={(event) => {
                  const checked = event.currentTarget.checked;
                  setChildrenChecked(checked);
                  setParam('audience', checked ? 'children' : 'all');
                }}
              />
              לילדים
            </label>
            {changed && (
              <button type="button" className="button ghost" onClick={clearFilters}>
                ניקוי סינון
              </button>
            )}
          </div>
        </div>
      </section>
      <section className="section">
        <div className="section-inner">
          <div className="section-heading">
            <h2>נמצאו {results.length} סרטים</h2>
            <Field label="מיון">
              <select value={filters.sort} onChange={(event) => setParam('sort', event.target.value)}>
                <option value="soonest">הקרוב ביותר</option>
                <option value="title">א׳-ת׳</option>
                <option value="release">תאריך בכורה</option>
              </select>
            </Field>
          </div>
          {results.length ? (
            <div className="poster-grid">
              {results.map((movie) => (
                <MoviePosterCard key={movie.id} movie={movie} activeCinemaSlug="glilot" />
              ))}
            </div>
          ) : (
            <EmptyState title="לא מצאנו סרטים בסינון הזה" body="נסו לבחור מתחם אחר או לנקות חלק מהמסננים." action="ניקוי סינון" onAction={clearFilters} />
          )}
        </div>
      </section>
    </>
  );
}

function MovieDetailPage() {
  const { movieSlug } = useParams();
  const { movies, cinemas, screenings } = useData();
  const { activeCinemaSlug } = useCinema();
  const navigate = useNavigate();
  const [date, setDate] = useState(FIXTURE_DATE);
  const [cinemaSlug, setCinemaSlug] = useState(activeCinemaSlug);
  const [experience, setExperience] = useState<Experience | 'all'>('all');
  const [trailerOpen, setTrailerOpen] = useState(false);
  const movie = movies.find((item) => item.slug === movieSlug);
  const cinema = cinemas.find((item) => item.slug === cinemaSlug);
  const detailScreenings = screenings.filter((screening) => {
    return (
      screening.movieId === movie?.id &&
      screening.cinemaId === cinema?.id &&
      toLocalDate(screening.startsAt) === date &&
      (experience === 'all' || screening.experience === experience)
    );
  });
  const related = movies.filter((item) => item.id !== movie?.id && item.genres.some((genre) => movie?.genres.includes(genre))).slice(0, 4);

  useDocumentTitle(movie ? `${movie.titleHe} | הקרנות וכרטיסים | סינמה סיטי` : 'העמוד לא נמצא | סינמה סיטי');

  if (!movie) return <NotFoundPage />;

  return (
    <>
      <section className="detail-hero">
        <div className="detail-hero-image">
          <img src={movie.backdropUrl} width="1920" height="799" alt="" />
        </div>
        <div className="section-inner detail-hero-content">
          <div className="detail-grid">
            <div className="detail-poster">
              <img src={movie.posterUrl} width="244" height="366" alt={`פוסטר הסרט ${movie.titleHe}`} />
            </div>
            <div>
              <p className="eyebrow">{movie.badges.join(' • ') || 'עכשיו בקולנוע'}</p>
              <h1 tabIndex={-1}>{movie.titleHe}</h1>
              <p className="muted ltr">{movie.titleOriginal}</p>
              <div className="chip-row" style={{ marginBlock: 16 }}>
                <StatusBadge>{movie.genres.join(' / ')}</StatusBadge>
                <StatusBadge tone="teal">{movie.runtimeMinutes} דקות</StatusBadge>
                <StatusBadge tone="sky">{movie.ageRestriction}</StatusBadge>
                <StatusBadge tone="teal">
                  <Volume2 size={14} aria-hidden="true" /> {movie.spokenLanguages.join(', ')}
                </StatusBadge>
              </div>
              <p>{movie.synopsisHe}</p>
              <div className="hero-actions">
                <Button variant="secondary" onClick={() => setTrailerOpen(true)}>
                  <Play size={18} aria-hidden="true" />
                  לצפייה בטריילר
                </Button>
                <a href="#showtimes" className="button primary">
                  להזמנת כרטיסים
                </a>
              </div>
            </div>
          </div>
        </div>
      </section>
      <section className="section" id="showtimes">
        <div className="section-inner showtime-tool">
          {movie.photosensitivityWarning && (
            <div className="alert">
              <Info aria-hidden="true" />
              <div>
                <h2>מידע חשוב לפני הצפייה</h2>
                <p>{movie.photosensitivityWarning}</p>
              </div>
            </div>
          )}
          <div className="booking-panel">
            <div className="section-heading">
              <h2>הקרנות</h2>
              <div className="chip-row">
                <Field label="מתחם">
                  <select value={cinemaSlug} onChange={(event) => setCinemaSlug(event.target.value)}>
                    {cinemas.map((item) => (
                      <option key={item.id} value={item.slug}>
                        {item.cityHe}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="פורמט">
                  <select value={experience} onChange={(event) => setExperience(event.target.value as Experience | 'all')}>
                    <option value="all">כל הפורמטים</option>
                    <option value="standard">רגיל</option>
                    <option value="vip">VIP</option>
                    <option value="prime">PRIME</option>
                    <option value="onyx">ONYX</option>
                  </select>
                </Field>
              </div>
            </div>
            <div className="chip-row" style={{ marginBlockEnd: 16 }}>
              {dateOptions(7).map((option) => (
                <button key={option} type="button" className={cn('chip', date === option && 'selected')} onClick={() => setDate(option)}>
                  {formatDate(option)}
                </button>
              ))}
            </div>
            {detailScreenings.length ? (
              <div className="showtime-tool">
                {detailScreenings.map((screening) => (
                  <div className="screening-row" key={screening.id}>
                    <div>
                      <StatusBadge tone={screening.experience === 'standard' ? 'gold' : screening.experience === 'vip' ? 'red' : screening.experience === 'prime' ? 'teal' : 'sky'}>
                        {experienceLabel(screening.experience)}
                      </StatusBadge>
                      <p className="metadata">
                        {screening.spokenLanguage}
                        {screening.subtitleLanguage ? ` • תרגום ${screening.subtitleLanguage}` : ''} • {screening.hallNameHe}
                      </p>
                    </div>
                    <div className="chip-row">
                      <ShowtimeChip screening={screening} onClick={() => navigate(`/booking?screening=${screening.id}`)} />
                      {screening.availability === 'low' && <span className="metadata">כמעט מלא</span>}
                      {screening.availability === 'sold-out' && <span className="metadata">אזל</span>}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState title="אין הקרנות בבחירה הזו" body="בחרו תאריך או פורמט אחר." />
            )}
          </div>
        </div>
      </section>
      {related.length > 0 && (
        <section className="section band">
          <div className="section-inner">
            <h2>אולי תאהבו גם</h2>
            <div className="poster-grid" style={{ marginBlockStart: 24 }}>
              {related.map((item) => (
                <MoviePosterCard key={item.id} movie={item} activeCinemaSlug={activeCinemaSlug} />
              ))}
            </div>
          </div>
        </section>
      )}
      <div className="section-inner mobile-sticky-cta">
        <a href="#showtimes" className="button primary" style={{ width: '100%' }}>
          להזמנת כרטיסים
        </a>
      </div>
      {trailerOpen && <TrailerDialog movie={movie} onClose={() => setTrailerOpen(false)} />}
    </>
  );
}

function CinemasPage() {
  const { cinemas } = useData();
  useDocumentTitle('מתחמי סינמה סיטי | שעות והקרנות');
  return (
    <>
      <section className="page-title-band">
        <div className="section-inner">
          <h1 tabIndex={-1}>מתחמי סינמה סיטי</h1>
          <p>שמונה מתחמים, מאות הקרנות, וחוויה שמתאימה לכל ערב.</p>
        </div>
      </section>
      <section className="section">
        <div className="section-inner list-grid">
          {cinemas.map((cinema) => {
            const openStatus = getOpenStatus(cinema);
            return (
              <Link to={`/cinemas/${cinema.slug}`} className="cinema-card" key={cinema.id}>
                <img src={cinema.imageUrl} width="640" height="360" alt={cinema.nameHe} loading="lazy" />
                <div className="cinema-card-caption">
                  <h2>{cinema.nameHe}</h2>
                  <p className="muted">{cinema.addressHe}</p>
                  <div className="chip-row">
                    <StatusBadge tone={openStatus.state === 'success' ? 'success' : openStatus.state === 'warning' ? 'gold' : 'teal'}>
                      {openStatus.label}
                    </StatusBadge>
                    {cinema.experiences.map((experience) => (
                      <StatusBadge key={experience} tone={experience === 'prime' ? 'teal' : experience === 'onyx' ? 'sky' : experience === 'vip' ? 'red' : 'gold'}>
                        {experienceLabel(experience)}
                      </StatusBadge>
                    ))}
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      </section>
    </>
  );
}

function CinemaDetailPage() {
  const { cinemaSlug } = useParams();
  const { cinemas, screenings, movies } = useData();
  const { setActiveCinemaSlug } = useCinema();
  const navigate = useNavigate();
  const [date, setDate] = useState(FIXTURE_DATE);
  const cinema = cinemas.find((item) => item.slug === cinemaSlug);
  useDocumentTitle(cinema ? `סינמה סיטי ${cinema.cityHe} | שעות והקרנות` : 'העמוד לא נמצא | סינמה סיטי');

  if (!cinema) return <NotFoundPage />;
  const openStatus = getOpenStatus(cinema);
  const todayScreenings = screenings.filter((screening) => screening.cinemaId === cinema.id && toLocalDate(screening.startsAt) === date);

  return (
    <>
      <section className="cinema-hero">
        <div className="cinema-hero-image">
          <img src={cinema.imageUrl} width="1280" height="480" alt="" />
        </div>
        <div className="section-inner cinema-hero-content">
          <div>
            <p className="eyebrow">{openStatus.label}</p>
            <h1 tabIndex={-1}>סינמה סיטי {cinema.cityHe}</h1>
            <p>{cinema.addressHe}</p>
            <div className="hero-actions">
              <a href="#cinema-showtimes" className="button primary" onClick={() => setActiveCinemaSlug(cinema.slug)}>
                להקרנות במתחם
              </a>
              <a href={cinema.mapUrl} target="_blank" rel="noreferrer" className="button secondary">
                <Navigation size={18} aria-hidden="true" />
                ניווט
              </a>
            </div>
          </div>
        </div>
      </section>
      <section className="section">
        <div className="section-inner">
          <div className="service-strip">
            <InfoRow icon={<Clock3 />} title="שעות היום" body={dailyHours(cinema)} />
            <InfoRow icon={<ParkingCircle />} title="חניה" body={cinema.parkingHe} />
            <InfoRow icon={<BusFront />} title="תחבורה ציבורית" body={cinema.publicTransportHe} />
            <InfoRow icon={<Accessibility />} title="נגישות" body={cinema.accessibilityHe} />
          </div>
        </div>
      </section>
      <section className="section band" id="cinema-showtimes">
        <div className="section-inner">
          <div className="section-heading">
            <h2>מה מקרינים היום</h2>
            <div className="chip-row">
              {dateOptions(7).map((option) => (
                <button type="button" key={option} className={cn('chip', date === option && 'selected')} onClick={() => setDate(option)}>
                  {formatDate(option)}
                </button>
              ))}
            </div>
          </div>
          {todayScreenings.length ? (
            <div className="showtime-tool">
              {Object.entries(groupBy(todayScreenings, (screening) => screening.movieId)).map(([movieId, group]) => {
                const movie = movies.find((item) => item.id === movieId);
                if (!movie || !group) return null;
                return (
                  <div className="screening-row" key={movieId}>
                    <div>
                      <strong>{movie.titleHe}</strong>
                      <p className="metadata">{movie.genres.join(' / ')} • {movie.runtimeMinutes} דקות</p>
                    </div>
                    <div className="chip-row">
                      {group.map((screening) => (
                        <ShowtimeChip
                          key={screening.id}
                          screening={screening}
                          onClick={() => {
                            setActiveCinemaSlug(cinema.slug);
                            navigate(`/booking?screening=${screening.id}`);
                          }}
                        />
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <EmptyState title="אין הקרנות בתאריך הזה" body="בחרו תאריך אחר או בדקו מתחם אחר." />
          )}
        </div>
      </section>
      <section className="section">
        <div className="section-inner two-column">
          <div className="showtime-tool">
            <h2>מידע על המתחם</h2>
            <p>{cinema.descriptionHe}</p>
            <h2>איך מגיעים</h2>
            <p>{cinema.publicTransportHe}</p>
            <h2>מה יש במתחם</h2>
            <div className="chip-row">
              {cinema.amenities.map((amenity) => (
                <StatusBadge key={amenity} tone="teal">
                  {amenity}
                </StatusBadge>
              ))}
            </div>
          </div>
          <div className="summary-panel">
            <h2>שעות פעילות</h2>
            <div className="summary-lines">
              {Object.entries(cinema.weeklyHours).map(([day, hours]) => (
                <div className="summary-line" key={day}>
                  <span>{hebrewDay(day)}</span>
                  <span className="ltr">{hours ? `${hours.open}-${hours.close}` : 'סגור'}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>
      <div className="section-inner mobile-sticky-cta">
        <Link to={`/booking?cinema=${cinema.slug}`} className="button primary" style={{ width: '100%' }}>
          להזמנת כרטיסים
        </Link>
      </div>
    </>
  );
}

function InfoRow({ icon, title, body }: { icon: ReactNode; title: string; body: string }) {
  return (
    <div className="service-item">
      <span aria-hidden="true">{icon}</span>
      <span>
        <strong>{title}</strong>
        <br />
        <span className="muted">{body}</span>
      </span>
    </div>
  );
}

function dailyHours(cinema: Cinema) {
  const day = new Intl.DateTimeFormat('en-US', { weekday: 'long', timeZone: 'Asia/Jerusalem' }).format(new Date()).toLowerCase();
  const hours = cinema.weeklyHours[day];
  return hours ? `${hours.open}-${hours.close}` : 'סגור היום';
}

function hebrewDay(day: string) {
  const labels: Record<string, string> = {
    sunday: 'ראשון',
    monday: 'שני',
    tuesday: 'שלישי',
    wednesday: 'רביעי',
    thursday: 'חמישי',
    friday: 'שישי',
    saturday: 'שבת',
  };
  return labels[day] ?? day;
}

function ExperiencesPage() {
  const { experiences, cinemas } = useData();
  useDocumentTitle('יותר מסרט | VIP, PRIME ו-ONYX | סינמה סיטי');
  return (
    <>
      <section className="page-title-band">
        <div className="section-inner">
          <h1 tabIndex={-1}>יותר מסרט</h1>
          <p>בחרו את חוויית הצפייה שמתאימה לערב שלכם.</p>
        </div>
      </section>
      <section className="section">
        <div className="section-inner experience-page">
          {experiences.map((experience) => (
            <section className="experience-section" id={experience.id} key={experience.id}>
              <div className="experience-copy">
                <p className="eyebrow">{experience.nameHe}</p>
                <h2>{experience.headingHe}</h2>
                <p>{experience.descriptionHe}</p>
                <div className="chip-row">
                  {experience.cinemaIds.map((cinemaId) => {
                    const cinema = cinemas.find((item) => item.id === cinemaId);
                    return cinema ? <StatusBadge key={cinema.id} tone={experience.accent}>{cinema.cityHe}</StatusBadge> : null;
                  })}
                  {experience.id === 'vip' && <StatusBadge tone="gold">מגיל 18</StatusBadge>}
                  {experience.id === 'onyx' && <StatusBadge tone="sky">4K LED</StatusBadge>}
                </div>
                <Link to={`/movies?experience=${experience.id}`} className="button primary">
                  {experience.id === 'vip' ? 'מצאו הקרנת VIP' : experience.id === 'prime' ? 'מצאו הקרנת PRIME' : 'להקרנות ONYX'}
                </Link>
              </div>
              <div className="experience-image">
                <img src={experience.imageUrl} width="560" height="420" alt={experience.headingHe} loading="lazy" />
              </div>
            </section>
          ))}
        </div>
      </section>
    </>
  );
}

function BookingProgress({ step }: { step: 1 | 2 | 3 | 4 }) {
  const steps = ['הקרנה', 'כרטיסים ומושבים', 'תשלום', 'אישור'];
  return (
    <div className="booking-progress">
      <div className="section-inner">
        <ol aria-label="שלבי הזמנה">
          {steps.map((label, index) => {
            const itemStep = (index + 1) as 1 | 2 | 3 | 4;
            return (
              <li key={label} className={cn(itemStep === step && 'active', itemStep < step && 'done')}>
                <span className="step-number">{itemStep}</span>
                <span>{label}</span>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}

function BookingScreeningPage() {
  const { movies, cinemas, screenings } = useData();
  const { activeCinemaSlug } = useCinema();
  const { draft, setDraft } = useBooking();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const initialScreening = screenings.find((screening) => screening.id === params.get('screening'));
  const [movieSlug, setMovieSlug] = useState(() => params.get('movie') ?? movies.find((movie) => movie.id === initialScreening?.movieId)?.slug ?? '');
  const [cinemaSlug, setCinemaSlug] = useState(() => params.get('cinema') ?? cinemas.find((cinema) => cinema.id === initialScreening?.cinemaId)?.slug ?? activeCinemaSlug);
  const [date, setDate] = useState(() => params.get('date') ?? (initialScreening ? toLocalDate(initialScreening.startsAt) : FIXTURE_DATE));
  const [experience, setExperience] = useState<Experience | 'all'>(() => (params.get('experience') as Experience | 'all') ?? initialScreening?.experience ?? 'all');
  const [selectedScreeningId, setSelectedScreeningId] = useState(() => params.get('screening') ?? draft.screeningId ?? '');
  useDocumentTitle('בוחרים הקרנה | סינמה סיטי');

  const movie = movies.find((item) => item.slug === movieSlug);
  const cinema = cinemas.find((item) => item.slug === cinemaSlug);
  const results = screenings.filter((screening) => {
    return (
      (!movie || screening.movieId === movie.id) &&
      (!cinema || screening.cinemaId === cinema.id) &&
      toLocalDate(screening.startsAt) === date &&
      (experience === 'all' || screening.experience === experience)
    );
  });
  const selectedScreening = screenings.find((screening) => screening.id === selectedScreeningId);

  useEffect(() => {
    const next = new URLSearchParams();
    if (movieSlug) next.set('movie', movieSlug);
    if (cinemaSlug) next.set('cinema', cinemaSlug);
    if (date) next.set('date', date);
    if (experience !== 'all') next.set('experience', experience);
    if (selectedScreeningId) next.set('screening', selectedScreeningId);
    setParams(next, { replace: true });
  }, [movieSlug, cinemaSlug, date, experience, selectedScreeningId, setParams]);

  function continueToSeats() {
    if (!selectedScreening) return;
    setDraft({
      ...emptyDraft,
      screeningId: selectedScreening.id,
    });
    trackEvent('booking_started', { screeningId: selectedScreening.id });
    navigate('/booking/seats');
  }

  return (
    <>
      <BookingProgress step={1} />
      <section className="page-title-band">
        <div className="section-inner">
          <h1 tabIndex={-1}>בוחרים הקרנה</h1>
          <p>בחרו סרט, מתחם, תאריך ופורמט. אחרי בחירת שעה תוכלו להמשיך למושבים.</p>
        </div>
      </section>
      <section className="section">
        <div className="section-inner booking-layout">
          <div className="booking-panel showtime-tool">
            <div className="filter-grid">
              <Field label="סרט">
                <select value={movieSlug} onChange={(event) => { setMovieSlug(event.target.value); setSelectedScreeningId(''); }}>
                  <option value="">כל הסרטים</option>
                  {movies.map((item) => (
                    <option key={item.id} value={item.slug}>
                      {item.titleHe}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="מתחם">
                <select value={cinemaSlug} onChange={(event) => { setCinemaSlug(event.target.value); setSelectedScreeningId(''); }}>
                  {cinemas.map((item) => (
                    <option key={item.id} value={item.slug}>
                      {item.cityHe}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="פורמט">
                <select value={experience} onChange={(event) => { setExperience(event.target.value as Experience | 'all'); setSelectedScreeningId(''); }}>
                  <option value="all">כל הפורמטים</option>
                  <option value="standard">רגיל</option>
                  <option value="vip">VIP</option>
                  <option value="prime">PRIME</option>
                  <option value="onyx">ONYX</option>
                </select>
              </Field>
            </div>
            <div className="chip-row">
              {dateOptions(7).map((option) => (
                <button key={option} type="button" className={cn('chip', date === option && 'selected')} onClick={() => { setDate(option); setSelectedScreeningId(''); }}>
                  {formatDate(option)}
                </button>
              ))}
            </div>
            {results.length ? (
              <div className="showtime-tool">
                {Object.entries(groupBy(results, (screening) => screening.movieId)).map(([movieId, group]) => {
                  const groupedMovie = movies.find((item) => item.id === movieId);
                  if (!groupedMovie || !group) return null;
                  return (
                    <div className="screening-row" key={movieId}>
                      <div>
                        <strong>{groupedMovie.titleHe}</strong>
                        <p className="metadata">{groupedMovie.titleOriginal}</p>
                      </div>
                      <div className="chip-row">
                        {group.map((screening) => (
                          <ShowtimeChip
                            key={screening.id}
                            screening={screening}
                            selected={selectedScreeningId === screening.id}
                            onClick={() => {
                              setSelectedScreeningId(screening.id);
                              trackEvent('showtime_selected', { screeningId: screening.id, context: 'booking' });
                            }}
                          />
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <EmptyState title="אין הקרנות בבחירה הזו" body="שנו סרט, מתחם או תאריך כדי למצוא הקרנה." />
            )}
          </div>
          <OrderSummary screening={selectedScreening} />
          <Button variant="primary" disabled={!selectedScreening} onClick={continueToSeats}>
            המשך לכרטיסים ומושבים
          </Button>
        </div>
      </section>
    </>
  );
}

function BookingSeatsPage() {
  const { screenings, movies, cinemas, seatMaps } = useData();
  const { draft, setDraft } = useBooking();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const screening = screenings.find((item) => item.id === draft.screeningId);
  const movie = movies.find((item) => item.id === screening?.movieId);
  const cinema = cinemas.find((item) => item.id === screening?.cinemaId);
  const seatMap = screening ? seatMaps[screening.seatMapId] : undefined;
  const ticketCount = totalTickets(draft.ticketQuantities);
  const [error, setError] = useState('');
  const expired = isDraftExpired(draft);
  useDocumentTitle('בוחרים כרטיסים ומושבים | סינמה סיטי');

  useEffect(() => {
    if (!screening) {
      navigate('/booking', { replace: true });
      showToast('בחרו הקרנה לפני בחירת מושבים.');
      return;
    }
    if (!draft.expiresAt) {
      setDraft((current) => ({ ...current, expiresAt: new Date(Date.now() + 15 * 60 * 1000).toISOString() }));
    }
  }, [screening, draft.expiresAt, navigate, setDraft, showToast]);

  if (!screening || !movie || !cinema || !seatMap) return null;
  const resolvedSeatMap = seatMap;

  function updateQuantity(ticketTypeId: string, delta: number) {
    setError('');
    setDraft((current) => {
      const currentQuantity = current.ticketQuantities[ticketTypeId] ?? 0;
      const nextQuantity = Math.max(0, currentQuantity + delta);
      const nextQuantities = { ...current.ticketQuantities, [ticketTypeId]: nextQuantity };
      const nextTotal = totalTickets(nextQuantities);
      if (nextTotal > 8) {
        showToast('ניתן להזמין עד 8 כרטיסים בהזמנה אחת.');
        return current;
      }
      trackEvent('ticket_quantity_changed', { ticketTypeId, quantity: nextQuantity });
      return {
        ...current,
        ticketQuantities: nextQuantities,
        selectedSeatIds: trimSeatsForTicketCount(current.selectedSeatIds, nextTotal),
      };
    });
  }

  function toggleSeat(seatId: string) {
    if (expired) return;
    const seat = resolvedSeatMap.seats.find((item) => item.id === seatId);
    if (!seat || seat.status === 'occupied') return;
    setDraft((current) => {
      if (current.selectedSeatIds.includes(seatId)) {
        trackEvent('seat_deselected', { seatId });
        return { ...current, selectedSeatIds: current.selectedSeatIds.filter((id) => id !== seatId) };
      }
      if (current.selectedSeatIds.length >= ticketCount) {
        showToast('בחרתם את מספר המושבים המרבי להזמנה זו');
        return current;
      }
      trackEvent('seat_selected', { seatId, kind: seat.kind });
      return { ...current, selectedSeatIds: [...current.selectedSeatIds, seatId] };
    });
  }

  function continueToCheckout() {
    if (ticketCount === 0) {
      setError('בחרו לפחות כרטיס אחד.');
      return;
    }
    if (draft.selectedSeatIds.length !== ticketCount) {
      setError('מספר המושבים חייב להתאים למספר הכרטיסים.');
      return;
    }
    navigate('/booking/checkout');
  }

  return (
    <>
      <BookingProgress step={2} />
      <section className="page-title-band">
        <div className="section-inner">
          <h1 tabIndex={-1}>בוחרים כרטיסים ומושבים</h1>
          <p>{movie.titleHe} • {cinema.nameHe} • <span className="ltr">{formatTime(screening.startsAt)}</span></p>
        </div>
      </section>
      <section className="section">
        <div className="section-inner booking-layout">
          <div className="booking-panel showtime-tool">
            {expired && (
              <div className="alert" role="alert">
                <CircleAlert aria-hidden="true" />
                <div>
                  <h2>הזמן לבחירת המושבים הסתיים</h2>
                  <p>כדי להציג זמינות עדכנית, בחרו שוב הקרנה ומושבים.</p>
                  <Button variant="secondary" onClick={() => navigate('/booking')}>
                    חזרה לבחירת הקרנה
                  </Button>
                </div>
              </div>
            )}
            <h2>כרטיסים</h2>
            {screening.ticketTypes.map((ticketType) => {
              const quantity = draft.ticketQuantities[ticketType.id] ?? 0;
              return (
                <div className="ticket-row" key={ticketType.id}>
                  <div>
                    <strong>{ticketType.labelHe}</strong>
                    {ticketType.noteHe && <p className="metadata">{ticketType.noteHe}</p>}
                  </div>
                  <div className="quantity-control" aria-label={`כמות ${ticketType.labelHe}`}>
                    <button type="button" className="quantity-button" aria-label={`הפחתת ${ticketType.labelHe}`} onClick={() => updateQuantity(ticketType.id, -1)} disabled={quantity === 0}>
                      <Minus size={16} aria-hidden="true" />
                    </button>
                    <span>{quantity}</span>
                    <button type="button" className="quantity-button" aria-label={`הוספת ${ticketType.labelHe}`} onClick={() => updateQuantity(ticketType.id, 1)} disabled={ticketCount >= 8}>
                      <Plus size={16} aria-hidden="true" />
                    </button>
                  </div>
                  <strong>{formatCurrency(quantity * ticketType.price)}</strong>
                </div>
              );
            })}
            <h2>מפת האולם</h2>
            <SeatLegend />
            <div className="screen-indicator">המסך</div>
            <div className="seat-tool">
              <SeatMapView seatMap={resolvedSeatMap} selectedSeatIds={draft.selectedSeatIds} onToggle={toggleSeat} />
            </div>
            {draft.selectedSeatIds.some((seatId) => resolvedSeatMap.seats.find((seat) => seat.id === seatId)?.kind === 'accessible') && (
              <p className="muted">
                בחרתם מושב נגיש. בגרסת ההדגמה הבחירה אינה נחסמת, אך בהגעה למתחם ייתכן שתידרש התאמה לזכאות.
              </p>
            )}
            <p className="field-error" role={error ? 'alert' : undefined}>
              {error}
            </p>
            <Button variant="primary" disabled={expired || ticketCount === 0 || draft.selectedSeatIds.length !== ticketCount} onClick={continueToCheckout}>
              המשך לתשלום
            </Button>
          </div>
          <OrderSummary screening={screening} />
        </div>
      </section>
    </>
  );
}

function SeatLegend() {
  return (
    <div className="seat-legend">
      <span>רגיל</span>
      <span style={{ color: 'var(--color-gold-400)' }}>נבחר / פרימיום</span>
      <span style={{ color: 'var(--color-teal-400)' }}>נגיש</span>
      <span style={{ color: 'var(--color-sky-300)' }}>מלווה</span>
      <span>תפוס</span>
    </div>
  );
}

function SeatMapView({
  seatMap,
  selectedSeatIds,
  onToggle,
}: {
  seatMap: SeatMap;
  selectedSeatIds: string[];
  onToggle: (seatId: string) => void;
}) {
  function focusSeat(row: string, number: number) {
    const button = document.querySelector<HTMLButtonElement>(`[data-seat-id="${row}${number}"]`);
    button?.focus();
  }

  function handleKey(event: KeyboardEvent<HTMLButtonElement>, row: string, number: number) {
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      focusSeat(row, Math.max(1, number - 1));
    }
    if (event.key === 'ArrowRight') {
      event.preventDefault();
      focusSeat(row, Math.min(seatMap.seatsPerRow, number + 1));
    }
    if (event.key === 'Home') {
      event.preventDefault();
      focusSeat(row, 1);
    }
    if (event.key === 'End') {
      event.preventDefault();
      focusSeat(row, seatMap.seatsPerRow);
    }
  }

  return (
    <div className="seat-map" role="group" aria-label="בחירת מושבים">
      {seatMap.rowLabels.map((row) => (
        <div className="seat-row" key={row}>
          {Array.from({ length: seatMap.seatsPerRow }, (_, index) => index + 1).map((number) => {
            const seat = seatMap.seats.find((item) => item.row === row && item.number === number)!;
            const selected = selectedSeatIds.includes(seat.id);
            return (
              <button
                key={seat.id}
                type="button"
                data-seat-id={seat.id}
                className={cn('seat-button', selected && 'selected', seat.status === 'occupied' && 'occupied', seat.kind)}
                disabled={seat.status === 'occupied'}
                aria-label={`שורה ${seat.row}, מושב ${seat.number}, ${selected ? 'נבחר' : seat.status === 'occupied' ? 'תפוס' : seat.kind === 'accessible' ? 'נגיש פנוי' : 'פנוי'}`}
                style={seatMap.aislesAfterSeatNumbers.includes(number) ? { marginInlineStart: 18 } : undefined}
                onClick={() => onToggle(seat.id)}
                onKeyDown={(event) => handleKey(event, row, number)}
              >
                {number}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}

function BookingCheckoutPage() {
  const { screenings } = useData();
  const { draft, setDraft, clearDraft } = useBooking();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const screening = screenings.find((item) => item.id === draft.screeningId);
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [paymentMethod, setPaymentMethod] = useState<'card' | 'voucher'>('card');
  const [terms, setTerms] = useState(false);
  const [marketing, setMarketing] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [orderSubmitted, setOrderSubmitted] = useState(false);
  useDocumentTitle('פרטים ותשלום | סינמה סיטי');

  useEffect(() => {
    if (orderSubmitted) return;
    if (!screening || totalTickets(draft.ticketQuantities) === 0 || draft.selectedSeatIds.length !== totalTickets(draft.ticketQuantities)) {
      navigate(screening ? '/booking/seats' : '/booking', { replace: true });
      showToast('השלימו בחירת הקרנה, כרטיסים ומושבים.');
      return;
    }
    trackEvent('checkout_viewed', { screeningId: screening.id });
  }, [draft.selectedSeatIds.length, draft.ticketQuantities, navigate, orderSubmitted, screening, showToast]);

  if (!screening) return null;
  const selectedScreening = screening;

  const discount = draft.voucherCode?.toUpperCase() === 'DEMO20' ? Math.min(20, calculateSubtotal(selectedScreening, draft.ticketQuantities)) : 0;
  const total = calculateTotal(selectedScreening, draft.ticketQuantities, discount);

  function validate() {
    const next: Record<string, string> = {};
    if (fullName.trim().length < 2) next.fullName = 'הזינו שם מלא.';
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) next.email = 'הזינו כתובת מייל תקינה.';
    if (!/^0?5\d[-\s]?\d{3}[-\s]?\d{4}$/.test(phone.replace(/\s/g, ''))) next.phone = 'הזינו מספר נייד ישראלי תקין.';
    if (!terms) next.terms = 'יש לאשר את תנאי הרכישה.';
    if (paymentMethod === 'voucher' && draft.voucherCode && draft.voucherCode.toUpperCase() !== 'DEMO20') next.voucher = 'הקוד אינו מוכר בגרסת ההדגמה';
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!validate()) {
      document.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
      return;
    }
    setOrderSubmitted(true);
    setSubmitting(true);
    await new Promise((resolve) => window.setTimeout(resolve, 700));
    const order: Order = {
      reference: `CC-${Math.floor(100000 + Math.random() * 899999)}`,
      email,
      fullName,
      phone,
      screeningId: selectedScreening.id,
      ticketLines: selectedScreening.ticketTypes
        .filter((ticketType) => (draft.ticketQuantities[ticketType.id] ?? 0) > 0)
        .map((ticketType) => ({
          ticketTypeId: ticketType.id,
          quantity: draft.ticketQuantities[ticketType.id] ?? 0,
          unitPrice: ticketType.price,
        })),
      seatIds: draft.selectedSeatIds,
      serviceFee: selectedScreening.serviceFee,
      discount,
      total,
      status: 'confirmed',
      createdAt: new Date().toISOString(),
    };
    window.sessionStorage.setItem(COMPLETED_ORDER_KEY, JSON.stringify(order));
    trackEvent('demo_order_confirmed', { screeningId: selectedScreening.id, total, marketing });
    navigate('/booking/confirmation', { replace: true });
    window.setTimeout(clearDraft, 0);
  }

  function applyVoucher(value: string) {
    setDraft((current) => ({
      ...current,
      voucherCode: value,
      discount: value.toUpperCase() === 'DEMO20' ? 20 : 0,
    }));
    if (value.toUpperCase() === 'DEMO20') trackEvent('voucher_applied', { value: 'DEMO20' });
  }

  return (
    <>
      <BookingProgress step={3} />
      <section className="page-title-band">
        <div className="section-inner">
          <h1 tabIndex={-1}>פרטים ותשלום</h1>
          <p>זהו תשלום מדומה בלבד. אין להזין פרטי אשראי אמיתיים.</p>
        </div>
      </section>
      <section className="section">
        <div className="section-inner booking-layout">
          <form className="form-panel showtime-tool" onSubmit={submit} noValidate>
            <h2>פרטי קשר</h2>
            <Field label="שם מלא" error={errors.fullName}>
              <input value={fullName} onChange={(event) => setFullName(event.target.value)} aria-invalid={Boolean(errors.fullName)} />
            </Field>
            <Field label="מייל" error={errors.email}>
              <input dir="ltr" value={email} onChange={(event) => setEmail(event.target.value)} aria-invalid={Boolean(errors.email)} />
            </Field>
            <Field label="טלפון נייד" error={errors.phone}>
              <input dir="ltr" value={phone} onChange={(event) => setPhone(event.target.value)} aria-invalid={Boolean(errors.phone)} />
            </Field>
            <h2>תשלום מדומה</h2>
            <div className="segmented" role="radiogroup" aria-label="שיטת תשלום">
              <button type="button" className={paymentMethod === 'card' ? 'active' : ''} onClick={() => setPaymentMethod('card')}>
                כרטיס אשראי לדוגמה
              </button>
              <button type="button" className={paymentMethod === 'voucher' ? 'active' : ''} onClick={() => setPaymentMethod('voucher')}>
                שובר לדוגמה
              </button>
            </div>
            {paymentMethod === 'card' ? (
              <div className="alert">
                <Info aria-hidden="true" />
                זהו אתר הדגמה. אין להזין פרטי אשראי אמיתיים. לחיצה על אישור תיצור הזמנה מדומה בלבד.
              </div>
            ) : (
              <Field label="קוד שובר לדוגמה" error={errors.voucher}>
                <input value={draft.voucherCode ?? ''} onChange={(event) => applyVoucher(event.target.value)} aria-invalid={Boolean(errors.voucher)} />
              </Field>
            )}
            <label style={{ display: 'flex', gap: 8, alignItems: 'start' }}>
              <input type="checkbox" checked={terms} onChange={(event) => setTerms(event.target.checked)} aria-invalid={Boolean(errors.terms)} />
              קראתי ואני מאשר/ת את תנאי הרכישה ואת מדיניות הביטולים.
            </label>
            {errors.terms && <p className="field-error" role="alert">{errors.terms}</p>}
            <label style={{ display: 'flex', gap: 8, alignItems: 'start' }}>
              <input type="checkbox" checked={marketing} onChange={(event) => setMarketing(event.target.checked)} />
              אשמח לקבל עדכונים והטבות מסינמה סיטי.
            </label>
            <Button type="submit" variant="primary" disabled={submitting}>
              {submitting ? 'טוען...' : `אישור הזמנה מדומה • ${formatCurrency(total)}`}
            </Button>
          </form>
          <OrderSummary screening={selectedScreening} discount={discount} />
        </div>
      </section>
    </>
  );
}

function BookingConfirmationPage() {
  const { screenings, movies, cinemas } = useData();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [order] = useState<Order | null>(() => readSessionJson(COMPLETED_ORDER_KEY, null));
  useDocumentTitle('הכרטיסים שלכם מוכנים | סינמה סיטי');

  useEffect(() => {
    if (!order) navigate('/booking', { replace: true });
  }, [navigate, order]);

  if (!order) return null;
  const completedOrder = order;
  const screening = screenings.find((item) => item.id === completedOrder.screeningId);
  const movie = movies.find((item) => item.id === screening?.movieId);
  const cinema = cinemas.find((item) => item.id === screening?.cinemaId);

  function copyReference() {
    navigator.clipboard?.writeText(completedOrder.reference);
    showToast('מספר ההזמנה הועתק.');
  }

  return (
    <>
      <BookingProgress step={4} />
      <section className="section">
        <div className="section-inner confirmation">
          <motion.div className="check-mark" initial={{ scale: 0.94 }} animate={{ scale: 1 }} transition={{ duration: 0.18 }}>
            <Check aria-hidden="true" />
          </motion.div>
          <h1 tabIndex={-1}>הכרטיסים שלכם מוכנים</h1>
          <p className="muted">שלחנו את פרטי ההזמנה לכתובת שהזנתם. בגרסת ההדגמה לא נשלח מייל בפועל.</p>
          <div className="tool-panel">
            <p className="eyebrow">מספר הזמנה</p>
            <h2 className="ltr">{completedOrder.reference}</h2>
            <IconButton label="העתקת מספר הזמנה" onClick={copyReference}>
              <Copy aria-hidden="true" />
            </IconButton>
          </div>
          <div className="two-column" style={{ width: '100%' }}>
            {movie && <img src={movie.posterUrl} width="160" height="240" alt={`פוסטר הסרט ${movie.titleHe}`} style={{ borderRadius: 8 }} />}
            <div className="summary-panel" style={{ position: 'static' }}>
              <h2>פרטי ההזמנה</h2>
              <div className="summary-lines">
                <SummaryLine label="סרט" value={movie?.titleHe ?? ''} />
                <SummaryLine label="מתחם" value={cinema?.nameHe ?? ''} />
                <SummaryLine label="שעה" value={screening ? `${formatDate(screening.startsAt, false)} ${formatTime(screening.startsAt)}` : ''} />
                <SummaryLine label="אולם" value={screening?.hallNameHe ?? ''} />
                <SummaryLine label="מושבים" value={completedOrder.seatIds.join(', ')} />
                <SummaryLine label="סה״כ" value={formatCurrency(completedOrder.total)} />
              </div>
            </div>
          </div>
          <div className="qr" aria-label="קוד כניסה מדומה">
            {Array.from({ length: 49 }, (_, index) => <span key={index} style={{ opacity: [0, 1, 2, 5, 6].includes(index % 7) || index % 5 === 0 ? 1 : 0 }} />)}
          </div>
          <div className="hero-actions">
            <Link to="/" className="button primary">
              חזרה לעמוד הבית
            </Link>
            <Link to="/manage-order" className="button secondary">
              ניהול ההזמנה
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}

function ManageOrderPage() {
  const { screenings, movies, cinemas } = useData();
  const { showToast } = useToast();
  const [reference, setReference] = useState('CC-482731');
  const [email, setEmail] = useState('demo@cinemacity.co.il');
  const [result, setResult] = useState<Order | null>(null);
  const [failed, setFailed] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const cancelledRefs = readJson<string[]>(CANCELLED_ORDERS_KEY, []);
  useDocumentTitle('בדיקה או ביטול הזמנה | סינמה סיטי');

  async function lookup(event: FormEvent) {
    event.preventDefault();
    const order = await cinemaRepository.findOrder(reference, email);
    trackEvent('manage_order_lookup', { found: Boolean(order) });
    if (!order) {
      setResult(null);
      setFailed(true);
      return;
    }
    setFailed(false);
    setResult(cancelledRefs.includes(order.reference) ? { ...order, status: 'cancelled' } : order);
  }

  function cancelOrder() {
    if (!result) return;
    const next = [...new Set([...cancelledRefs, result.reference])];
    writeJson(CANCELLED_ORDERS_KEY, next);
    setResult({ ...result, status: 'cancelled' });
    setConfirmOpen(false);
    trackEvent('demo_order_cancelled', { reference: result.reference });
    showToast('ההזמנה בוטלה בגרסת ההדגמה.');
  }

  const screening = screenings.find((item) => item.id === result?.screeningId);
  const movie = movies.find((item) => item.id === screening?.movieId);
  const cinema = cinemas.find((item) => item.id === screening?.cinemaId);

  return (
    <>
      <section className="page-title-band">
        <div className="section-inner">
          <h1 tabIndex={-1}>בדיקה או ביטול הזמנה</h1>
          <p>הזינו מספר הזמנה ומייל. בגרסת ההדגמה קיימת הזמנה אחת לבדיקה.</p>
        </div>
      </section>
      <section className="section">
        <div className="section-inner booking-layout">
          <form className="form-panel showtime-tool" onSubmit={lookup}>
            <Field label="מספר הזמנה">
              <input className="ltr" value={reference} onChange={(event) => setReference(event.target.value)} />
            </Field>
            <Field label="מייל">
              <input className="ltr" value={email} onChange={(event) => setEmail(event.target.value)} />
            </Field>
            <Button type="submit" variant="primary">
              בדיקה
            </Button>
            {failed && <p className="field-error" role="alert">לא מצאנו הזמנה שתואמת לפרטים. בדקו את מספר ההזמנה ואת כתובת המייל.</p>}
          </form>
          {result ? (
            <aside className="summary-panel" aria-labelledby="manage-summary">
              <h2 id="manage-summary">הזמנה {result.reference}</h2>
              <div className="summary-lines">
                <SummaryLine label="סטטוס" value={result.status === 'cancelled' ? 'בוטלה' : 'מאושרת'} />
                <SummaryLine label="סרט" value={movie?.titleHe ?? ''} />
                <SummaryLine label="מתחם" value={cinema?.nameHe ?? ''} />
                <SummaryLine label="שעה" value={screening ? `${formatDate(screening.startsAt, false)} ${formatTime(screening.startsAt)}` : ''} />
                <SummaryLine label="מושבים" value={result.seatIds.join(', ')} />
                <SummaryLine label="סה״כ" value={formatCurrency(result.total)} />
              </div>
              <div className="hero-actions">
                <Button variant="danger" disabled={result.status === 'cancelled'} onClick={() => setConfirmOpen(true)}>
                  <Trash2 size={18} aria-hidden="true" />
                  ביטול הזמנה
                </Button>
                <Link to="/movies" className="button ghost">
                  חזרה לסרטים
                </Link>
              </div>
              {result.status === 'cancelled' && <p className="muted">ההזמנה בוטלה בגרסת ההדגמה.</p>}
            </aside>
          ) : (
            <EmptyState title="מוכנים לבדיקה" body="מספר ההזמנה לדוגמה הוא CC-482731 והמייל הוא demo@cinemacity.co.il." />
          )}
        </div>
      </section>
      {confirmOpen && (
        <Modal title="לבטל את ההזמנה?" labelledBy="cancel-order-title" onClose={() => setConfirmOpen(false)}>
          <p>הפעולה תשנה את סטטוס ההזמנה בדפדפן הזה. לא יתבצע זיכוי אמיתי.</p>
          <div className="hero-actions">
            <Button variant="secondary" onClick={() => setConfirmOpen(false)}>
              השאירו את ההזמנה
            </Button>
            <Button variant="danger" onClick={cancelOrder}>
              ביטול הזמנה מדומה
            </Button>
          </div>
        </Modal>
      )}
    </>
  );
}

function OrderSummary({ screening, discount = 0 }: { screening?: Screening | null; discount?: number }) {
  const { movies, cinemas } = useData();
  const { draft } = useBooking();
  const movie = movies.find((item) => item.id === screening?.movieId);
  const cinema = cinemas.find((item) => item.id === screening?.cinemaId);
  const subtotal = screening ? calculateSubtotal(screening, draft.ticketQuantities) : 0;
  const total = screening ? calculateTotal(screening, draft.ticketQuantities, discount || draft.discount) : 0;

  return (
    <aside className="summary-panel" aria-labelledby="order-summary-heading">
      <h2 id="order-summary-heading">סיכום הזמנה</h2>
      {screening && movie && cinema ? (
        <>
          <div className="summary-lines">
            <SummaryLine label="סרט" value={movie.titleHe} />
            <SummaryLine label="מקור" value={movie.titleOriginal} ltr />
            <SummaryLine label="מתחם" value={cinema.nameHe} />
            <SummaryLine label="אולם" value={screening.hallNameHe} />
            <SummaryLine label="תאריך" value={formatDate(screening.startsAt, false)} />
            <SummaryLine label="שעה" value={formatTime(screening.startsAt)} ltr />
            {screening.ticketTypes
              .filter((ticketType) => (draft.ticketQuantities[ticketType.id] ?? 0) > 0)
              .map((ticketType) => (
                <SummaryLine
                  key={ticketType.id}
                  label={`${ticketType.labelHe} x ${draft.ticketQuantities[ticketType.id]}`}
                  value={formatCurrency(ticketType.price * (draft.ticketQuantities[ticketType.id] ?? 0))}
                />
              ))}
            {draft.selectedSeatIds.length > 0 && <SummaryLine label="מושבים" value={draft.selectedSeatIds.join(', ')} ltr />}
            <SummaryLine label="דמי שירות" value={formatCurrency(screening.serviceFee)} />
            {(discount || draft.discount) > 0 && <SummaryLine label="הנחה" value={`-${formatCurrency(discount || draft.discount)}`} />}
            <SummaryLine label="ביניים" value={formatCurrency(subtotal)} />
          </div>
          <div className="summary-total" aria-live="polite">
            <span>סה״כ</span>
            <span>{formatCurrency(total)}</span>
          </div>
        </>
      ) : (
        <p className="muted">בחרו הקרנה כדי לראות את פרטי ההזמנה.</p>
      )}
    </aside>
  );
}

function SummaryLine({ label, value, ltr = false }: { label: string; value: string; ltr?: boolean }) {
  return (
    <div className="summary-line">
      <span>{label}</span>
      <span className={ltr ? 'ltr' : undefined}>{value}</span>
    </div>
  );
}

function TrailerDialog({ movie, onClose }: { movie: Movie; onClose: () => void }) {
  return (
    <Modal title={`טריילר: ${movie.titleHe}`} labelledBy="trailer-title" onClose={onClose}>
      {movie.trailerUrl ? (
        <iframe
          width="100%"
          height="315"
          src={movie.trailerUrl}
          title={`טריילר הסרט ${movie.titleHe}`}
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowFullScreen
          style={{ border: 0, borderRadius: 8 }}
        />
      ) : (
        <div className="empty-state">
          <img src={movie.posterUrl} width="160" height="240" alt={`פוסטר הסרט ${movie.titleHe}`} />
          <p>הטריילר אינו זמין כרגע</p>
        </div>
      )}
    </Modal>
  );
}

function EmptyState({
  title,
  body,
  action,
  onAction,
}: {
  title: string;
  body: string;
  action?: string;
  onAction?: () => void;
}) {
  return (
    <div className="empty-state">
      <Film size={38} aria-hidden="true" />
      <h2>{title}</h2>
      <p className="muted">{body}</p>
      {action && onAction && (
        <Button variant="secondary" onClick={onAction}>
          {action}
        </Button>
      )}
    </div>
  );
}

function NotFoundPage() {
  useDocumentTitle('העמוד לא נמצא | סינמה סיטי');
  return (
    <section className="section">
      <div className="section-inner empty-state">
        <Film size={42} aria-hidden="true" />
        <h1 tabIndex={-1}>העמוד לא נמצא</h1>
        <p className="muted">יכול להיות שהקישור השתנה או שהתוכן כבר אינו זמין.</p>
        <div className="hero-actions">
          <Link to="/movies" className="button primary">
            לכל הסרטים
          </Link>
          <Link to="/" className="button secondary">
            לעמוד הבית
          </Link>
        </div>
      </div>
    </section>
  );
}
