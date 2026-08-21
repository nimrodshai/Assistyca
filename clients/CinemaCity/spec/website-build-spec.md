# Cinema City Israel Website Redesign

Implementation-ready product, UX, UI, content, and engineering specification

| Field | Value |
| --- | --- |
| Status | Build-ready concept specification |
| Prepared | 2026-08-21 |
| Primary locale | Hebrew, Israel |
| Direction | RTL |
| Product type | Cinema discovery and ticket-booking website |
| Build target | Responsive frontend prototype with a simulated booking flow |
| Fixture source | `fixture-data.json` in this directory |

## 1. Instructions for the implementation model

Build the site described in this document. Do not redesign the product, change the route list, replace the visual direction, or invent new business rules. Use `fixture-data.json` as the only runtime content source for the prototype.

Use this priority order if two requirements conflict:

1. Booking correctness and accessibility.
2. Responsive behavior and readable Hebrew RTL layout.
3. Visual direction and motion.
4. Optional content and decorative detail.

The word **must** marks an acceptance requirement. The word **may** marks optional polish. Complete every required route, state, and interaction before adding optional effects.

The prototype must run without a private Cinema City API, account, payment gateway, or environment variable. It must use deterministic local fixtures. A production integration can replace the repository layer later without changing page components.

## 2. Source facts and design assumptions

### 2.1 Official source facts

Research date: 2026-08-21.

The current official Cinema City Israel site supplies the following business facts:

- The brand operates eight listed locations: Glilot, Rishon LeZion, Jerusalem, Kfar Saba, Netanya, Hadera, Be'er Sheva, and Ashdod.
- Users can browse movies, children’s content, locations, VIP, events, and showtimes by hour.
- Users can start an order by cinema or by movie.
- The VIP experience appears in Glilot, Rishon LeZion, Jerusalem, and Be'er Sheva.
- Cinema PRIME appears in Netanya, Hadera, and Kfar Saba.
- The ONYX 4K LED auditorium appears in Glilot.
- Movie records include Hebrew and original titles, synopsis, genre, runtime, release date, viewing restriction, trailer, and screenings.
- The site links to ticket verification or cancellation, accessibility information, privacy information, and contact content.

Official references:

- [Cinema City Israel homepage](https://www.cinema-city.co.il/)
- [Movies](https://www.cinema-city.co.il/movies)
- [Locations](https://www.cinema-city.co.il/locations)
- [Showtimes by hour](https://www.cinema-city.co.il/timehour/)
- [VIP and PRIME](https://www.cinema-city.co.il/Page/10/)
- [ONYX](https://www.cinema-city.co.il/onyx)

### 2.2 Prototype decisions

The following items are design decisions for this prototype. They do not claim to describe the current production system:

- Prices, availability, seat maps, order numbers, and screening inventory are sample data.
- The prototype stores the selected cinema, cookie choice, and active booking draft in local storage.
- The checkout screen simulates payment. It must never request or store a real card number.
- The manage-order screen simulates lookup and cancellation.
- Search uses local fixture data.
- The site supports Hebrew UI only in this phase. Original movie titles can appear in English.
- The site does not include user accounts, loyalty points, food pre-ordering, gift cards, or real voucher validation.

## 3. Product brief

### 3.1 Product promise

Cinema City helps a visitor choose a movie and secure seats with the fewest decisions possible. The homepage must answer three questions within the first viewport:

1. Which cinema am I using?
2. Which movies can I watch soon?
3. How do I start an order?

### 3.2 Primary user jobs

- Find a movie playing near the user today or this week.
- Compare showtimes without opening many pages.
- Distinguish Hebrew-dubbed, subtitled, VIP, PRIME, ONYX, and standard screenings.
- Choose ticket quantities and seats.
- Review the order before confirming a simulated purchase.
- Find location hours, address, parking, public transport, and available experiences.
- Retrieve or cancel an existing order in the prototype.

### 3.3 Audience

- Mobile-first customers buying on the way to the cinema.
- Parents comparing dubbed children’s movies and suitable times.
- Couples and groups comparing premium experiences.
- Customers with accessibility needs who require keyboard access, accessible-seat information, and clear warnings.
- Desktop users planning a later visit and comparing several movies or locations.

### 3.4 Success criteria

The prototype succeeds when a new visitor can complete these tasks without instruction text:

- Select Glilot, choose a Spider-Man screening, select two adult tickets and two adjacent seats, and reach confirmation.
- Filter the movie catalog to children’s movies and find a Hebrew-dubbed screening.
- switch the active cinema from the header and see showtimes update across the home and movie detail pages.
- Open the Glilot page and find opening hours, address, directions, and ONYX availability.
- Look up the fixture order `CC-482731` and see its order details.

## 4. Scope

### 4.1 Required deliverable

Build a polished frontend prototype containing:

- A responsive RTL application shell.
- A full-bleed, poster-led homepage.
- Movie catalog and filtering.
- Movie detail and showtime selection.
- Cinema list and cinema detail pages.
- A premium experiences page for VIP, PRIME, and ONYX.
- A four-step booking flow: screening, tickets and seats, checkout, confirmation.
- Search overlay.
- Manage-order lookup.
- Cookie consent.
- Loading, empty, validation, expired-draft, and generic error states.
- Local state persistence.
- Unit and end-to-end tests for the core flow.

### 4.2 Out of scope

- Real authentication.
- Real payment collection.
- Real voucher redemption.
- Real seat locking or inventory concurrency.
- A content management system.
- A Cinema City employee portal.
- Email or SMS delivery.
- A production analytics vendor.
- A second language.
- Event venue rental and birthday booking forms.

Do not add placeholder screens for out-of-scope features. Link external or future items from the footer only when the specification names a destination.

## 5. Experience concept

### 5.1 Concept name

**The Lobby Starts Here**

The interface should feel like entering a cinema lobby after dark. Large film artwork creates the atmosphere. Warm marquee light identifies active choices. A red booking rail behaves like the ticket counter. The rest of the interface uses quiet dark surfaces so posters and screening times stay legible.

### 5.2 Memorable device

Use a continuous red booking rail across the bottom of the homepage hero. The rail remains visually connected to the primary red ticket button in the header. On movie pages, the same rail becomes a sticky showtime summary. On booking pages, it becomes the order progress strip. This repeated shape should make the purchase path recognizable.

### 5.3 Visual character

- Cinematic, editorial, confident, and warm.
- Dark without relying on blue-gray dashboard styling.
- Dense enough for fast comparison.
- Poster-first rather than card-first.
- Precise 1 px rules, compact labels, and rectangular controls with a maximum 8 px radius.
- Red marks purchase actions. Gold marks selected or premium states. Teal marks accessible information. Off-white carries body text.

### 5.4 Avoid

- Purple gradients.
- Floating decorative orbs.
- Glassmorphism.
- Oversized marketing copy that pushes showtimes below the fold.
- Generic rounded cards around every section.
- Nested cards.
- Horizontal scroll on the page.
- Manually drawn icons when Lucide provides the symbol.
- Generic stock photos that do not show a movie, auditorium, or Cinema City location.
- Text rendered inside hero artwork. Keep critical copy in HTML.

## 6. Brand and design system

### 6.1 Logo

Use the official Cinema City logo as a local transparent asset named `cinema-city-logo.png` or `cinema-city-logo.webp`.

Prototype source:

`https://www.cinema-city.co.il/img/cinema-logo.png`

Download the asset during implementation and serve it locally. Do not hotlink it at runtime. Show the logo at 104 x 72 px on desktop and 76 x 52 px on mobile. Preserve its aspect ratio and transparent background.

### 6.2 Color tokens

Define these tokens in `src/styles/tokens.css` and use no untracked hard-coded colors in components.

```css
:root {
  --color-ink-950: #090910;
  --color-ink-900: #11111c;
  --color-ink-850: #171725;
  --color-ink-800: #202033;
  --color-paper: #f7f4ec;
  --color-paper-muted: #c9c6bd;
  --color-red-600: #dd3548;
  --color-red-700: #bc2437;
  --color-gold-400: #f2c55c;
  --color-gold-500: #dba83e;
  --color-teal-400: #4dc8bd;
  --color-sky-300: #8ec9e8;
  --color-success: #58b77b;
  --color-warning: #f2c55c;
  --color-danger: #f06464;
  --color-border: rgba(247, 244, 236, 0.18);
  --color-border-strong: rgba(247, 244, 236, 0.34);
  --color-overlay: rgba(9, 9, 16, 0.66);
  --shadow-elevated: 0 18px 48px rgba(0, 0, 0, 0.38);
  --radius-control: 6px;
  --radius-card: 8px;
}
```

Usage rules:

- `--color-ink-950` is the page background.
- `--color-ink-900` and `--color-ink-850` separate content bands.
- `--color-red-600` is reserved for purchase CTAs, destructive confirmation, and the booking rail.
- `--color-gold-400` marks selected dates, selected seats, premium labels, and focus accents.
- `--color-teal-400` marks accessibility and available accessible seats.
- Body text uses `--color-paper`; secondary text uses `--color-paper-muted`.
- A component may use one semantic accent at a time.

### 6.3 Typography

Use fonts with full Hebrew support:

- Display and headings: `Secular One`, fallback `Arial Hebrew`, sans-serif.
- Body, labels, inputs, and numbers: `Rubik`, fallback `Arial Hebrew`, sans-serif.

Load the fonts through `@fontsource/secular-one` and `@fontsource/rubik`, or place licensed WOFF2 files in `src/assets/fonts`. Do not depend on a remote font request at runtime.

Set `letter-spacing: 0` for all text. Do not scale font size with viewport width.

| Role | Desktop | Mobile | Weight | Line height |
| --- | ---: | ---: | ---: | ---: |
| Hero movie title | 56 px | 36 px | 400 display | 1.08 |
| Page H1 | 42 px | 32 px | 400 display | 1.12 |
| Section H2 | 30 px | 25 px | 400 display | 1.2 |
| Card title | 20 px | 18 px | 600 body | 1.25 |
| Body large | 18 px | 17 px | 400 | 1.55 |
| Body | 16 px | 16 px | 400 | 1.55 |
| Label | 14 px | 14 px | 600 | 1.3 |
| Caption | 13 px | 13 px | 400 | 1.35 |
| Showtime | 16 px | 16 px | 600 | 1 |

Clamp long movie titles to two lines in cards. Show the full title in a tooltip and accessible name. Do not reduce card title text below 16 px.

### 6.4 Spacing

Use an 8 px base grid.

```css
--space-1: 4px;
--space-2: 8px;
--space-3: 12px;
--space-4: 16px;
--space-5: 24px;
--space-6: 32px;
--space-7: 48px;
--space-8: 64px;
--space-9: 96px;
```

Section padding:

- Desktop: 72 px block.
- Tablet: 56 px block.
- Mobile: 40 px block.

Content width:

- Maximum: 1280 px.
- Desktop side gutter: 32 px.
- Tablet side gutter: 24 px.
- Mobile side gutter: 16 px.

### 6.5 Borders, depth, and texture

- Use 1 px borders for controls, filter bars, list rows, and ticket summaries.
- Use the elevated shadow only for overlays, drawers, the booking rail, and the checkout summary.
- Poster cards use no outer background panel. The artwork, title, and metadata form the item.
- Use a subtle local noise texture over dark full-width bands at 3 to 5 percent opacity. The texture must not reduce text contrast.
- Use solid translucent overlays on hero images. Do not use a gradient as the hero background.

### 6.6 Icons

Use `lucide-react` icons. Set `aria-hidden="true"` on decorative icons. Give icon-only buttons an `aria-label` and a visible tooltip.

Required icons:

- Search
- MapPin
- CalendarDays
- Clock3
- Ticket
- Menu
- X
- ChevronLeft and ChevronRight, adjusted for RTL meaning
- Play
- Accessibility
- Armchair
- Volume2 or Languages for language labels
- Info
- CircleAlert
- Check
- Plus and Minus
- Trash2
- Navigation
- ParkingCircle
- BusFront

## 7. Technical implementation

### 7.1 Application location

Create the application at:

`clients/CinemaCity/site/`

The site must run independently from the repository root.

### 7.2 Stack

- Vite
- React
- TypeScript with strict mode
- React Router DOM
- `lucide-react`
- `motion` for the hero entrance and route transitions
- Plain CSS organized by tokens, global layout, and component files
- Vitest and React Testing Library
- Playwright for browser acceptance tests

Do not add Tailwind, a UI component framework, a carousel library, Redux, Zustand, a date library, or a form library. Native React state, context, and browser APIs cover this prototype.

### 7.3 Required scripts

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "lint": "eslint .",
    "test": "vitest run",
    "test:e2e": "playwright test"
  }
}
```

### 7.4 File structure

```text
clients/CinemaCity/site/
  public/
    images/
      brand/
      heroes/
      posters/
      locations/
      experiences/
      texture/
  src/
    app/
      App.tsx
      router.tsx
      AppProviders.tsx
    assets/
      fonts/
    components/
      app-shell/
        Header.tsx
        MobileNav.tsx
        Footer.tsx
        CookieBanner.tsx
      booking/
        BookingRail.tsx
        BookingProgress.tsx
        OrderSummary.tsx
        TicketQuantity.tsx
        SeatMap.tsx
        SeatLegend.tsx
        DraftExpiryNotice.tsx
      cinema/
        CinemaSwitcher.tsx
        CinemaCard.tsx
        CinemaInfoRow.tsx
      movie/
        MoviePosterCard.tsx
        MovieLandscapeCard.tsx
        MovieMetadata.tsx
        ShowtimeChip.tsx
        ShowtimeGroup.tsx
        FilterBar.tsx
      overlays/
        SearchDialog.tsx
        TrailerDialog.tsx
        ConfirmDialog.tsx
        ToastRegion.tsx
      ui/
        Button.tsx
        IconButton.tsx
        SelectField.tsx
        TextField.tsx
        SegmentedControl.tsx
        StatusBadge.tsx
        Skeleton.tsx
        EmptyState.tsx
        ErrorState.tsx
    context/
      CinemaContext.tsx
      BookingContext.tsx
      ToastContext.tsx
    data/
      fixture-data.json
      cinemaRepository.ts
      fixtureCinemaRepository.ts
      types.ts
    hooks/
      useDocumentTitle.ts
      useMediaQuery.ts
      useReducedMotion.ts
      useStorageState.ts
    pages/
      HomePage.tsx
      MoviesPage.tsx
      MovieDetailPage.tsx
      CinemasPage.tsx
      CinemaDetailPage.tsx
      ExperiencesPage.tsx
      BookingScreeningPage.tsx
      BookingSeatsPage.tsx
      BookingCheckoutPage.tsx
      BookingConfirmationPage.tsx
      ManageOrderPage.tsx
      NotFoundPage.tsx
    styles/
      tokens.css
      reset.css
      global.css
      utilities.css
    test/
      setup.ts
    main.tsx
  tests/
    booking-flow.spec.ts
    responsive.spec.ts
    accessibility.spec.ts
  index.html
  package.json
  tsconfig.json
  vite.config.ts
  playwright.config.ts
```

Copy the supplied `fixture-data.json` from the spec directory into `src/data/fixture-data.json`. Keep the source fixture unchanged.

### 7.5 Data access boundary

Page components must not import JSON. They call a `CinemaRepository` interface.

```ts
export interface CinemaRepository {
  getHome(): Promise<HomePayload>;
  listMovies(filters?: MovieFilters): Promise<Movie[]>;
  getMovie(slug: string): Promise<Movie | null>;
  listCinemas(): Promise<Cinema[]>;
  getCinema(slug: string): Promise<Cinema | null>;
  listScreenings(query: ScreeningQuery): Promise<Screening[]>;
  getScreening(id: string): Promise<Screening | null>;
  findOrder(reference: string, email: string): Promise<Order | null>;
}
```

`FixtureCinemaRepository` must simulate an asynchronous request with a 180 ms delay. Keep that delay in one helper so tests can disable it.

## 8. Routes

| Route | Page | Purpose |
| --- | --- | --- |
| `/` | Home | Featured movie, fast booking, movie discovery, locations, premium experiences |
| `/movies` | Movies | Browse and filter all fixture movies |
| `/movies/:movieSlug` | Movie detail | Trailer, metadata, synopsis, warnings, and grouped showtimes |
| `/cinemas` | Cinemas | Browse all eight locations |
| `/cinemas/:cinemaSlug` | Cinema detail | Hours, address, amenities, experiences, and current showtimes |
| `/experiences` | Experiences | Compare VIP, PRIME, and ONYX |
| `/booking` | Screening step | Confirm movie, cinema, date, format, and showtime |
| `/booking/seats` | Tickets and seats | Choose ticket quantities and seats |
| `/booking/checkout` | Checkout | Contact details, mock payment, consent, and review |
| `/booking/confirmation` | Confirmation | Display the generated fixture order |
| `/manage-order` | Manage order | Find fixture order and simulate cancellation |
| `*` | Not found | Recover to movies or homepage |

Use path routes, not hash routes. Vite preview and the deployment host must fall back to `index.html` for client routes.

### 8.1 Booking URL contract

Use these search parameters when linking into `/booking`:

| Parameter | Value | Example |
| --- | --- | --- |
| `movie` | Movie slug | `spider-man-brand-new-day` |
| `cinema` | Cinema slug | `glilot` |
| `date` | Local date in `YYYY-MM-DD` | `2026-08-21` |
| `experience` | Experience ID | `standard` |
| `screening` | Screening ID | `scr-spider-glilot-20260821-2030` |

The `screening` parameter wins when it points to a valid record. Derive movie, cinema, date, and experience from that record and replace conflicting parameters. Ignore unknown values and keep the rest of the page usable. Update the URL with `replace` while the user changes filters and use `push` only after the user selects a screening or changes routes.

## 9. Global application shell

### 9.1 HTML root

```html
<html lang="he" dir="rtl">
```

Set `color-scheme: dark`. Set the body background to `--color-ink-950`. The app must not flash a white background during load.

### 9.2 Skip link

The first focusable element must be a skip link with exact copy:

`דלגו לתוכן הראשי`

It stays offscreen until focused and then appears 12 px from the top-right edge.

### 9.3 Desktop header

Height: 76 px. Position: sticky at the top. Z-index: 50.

Right-to-left visual order:

1. Cinema City logo.
2. Primary navigation: `סרטים`, `מתחמים`, `VIP וחוויות`, `ילדים`.
3. Flexible spacer.
4. Active cinema button with MapPin icon and selected cinema name.
5. Search icon button.
6. `ניהול הזמנה` text link.
7. Red primary button with Ticket icon and copy `להזמנת כרטיסים`.

Header behavior:

- Start with a transparent dark overlay on the homepage hero.
- Change to `rgba(9, 9, 16, 0.96)` with a bottom border after 40 px scroll.
- Use the opaque state on all inner routes.
- The logo links to `/`.
- The active nav link uses a 2 px gold underline.
- The active cinema button opens `CinemaSwitcher` as a popover on desktop.
- The search button opens `SearchDialog`.
- The red button opens `/booking` and keeps any valid draft.

### 9.4 Mobile header

Height: 64 px. Position: sticky. Layout:

- Menu icon at the right.
- Centered logo.
- Red ticket icon button at the left.

The ticket button uses `aria-label="להזמנת כרטיסים"` and a tooltip on pointer hover. The menu opens a full-height drawer from the right. The drawer includes navigation, selected cinema, manage order, contact, accessibility, and privacy links.

The mobile drawer must trap focus, close on Escape, close after navigation, and return focus to the menu button.

### 9.5 Footer

Use a full-width `--color-ink-900` band with a 1 px top border. Do not wrap the whole footer in a card.

Desktop layout uses four columns:

- Brand: logo, `עיר הסרטים של ישראל`, social icon placeholders.
- Discover: movies, cinemas, VIP and experiences, children.
- Service: manage order, contact, FAQ, accessibility.
- Legal: terms, privacy, camera policy, accessibility statement.

Add a compact newsletter row below the columns with email input, consent checkbox, and `הרשמה` button. Submission validates the email and shows a toast. It does not call a service.

Bottom line copy:

`© 2026 ניו לינאו סינמה (2006) בע״מ. קונספט עיצובי לצורכי הדגמה.`

### 9.6 Cookie banner

Show the cookie banner on first visit. Store the choice under `cinemaCity.cookieConsent.v1`.

Desktop: bottom band with text and actions in one row.

Mobile: bottom sheet with 16 px padding.

Exact copy:

Title: `עוגיות, בלי דרמה`

Body: `אנחנו משתמשים בעוגיות כדי לשפר את חוויית הגלישה, למדוד שימוש ולהתאים תוכן. תוכלו לאשר הכול או להמשיך עם עוגיות חיוניות בלבד.`

Actions:

- Primary: `אישור הכול`
- Secondary: `חיוניות בלבד`
- Text link: `מדיניות פרטיות`

Both buttons dismiss the banner and store the selected value. The banner must not cover the mobile booking CTA; add bottom page padding while it is visible.

## 10. Homepage

### 10.1 First viewport

The first viewport contains the sticky header, full-bleed movie hero, booking rail, and a visible hint of the `עכשיו בקולנוע` section.

Desktop hero height:

`height: clamp(470px, 66svh, 590px)`

Mobile hero height:

`height: clamp(430px, 64svh, 520px)`

Use the Spider-Man fixture backdrop as the initial hero image. Cover the full hero. Position the image center at `50% 38%` on desktop and `62% 50%` on mobile. Place one solid `rgba(9, 9, 16, 0.48)` overlay over the full image and a second solid `rgba(9, 9, 16, 0.72)` panel behind only the copy area. Do not use a CSS gradient.

Hero copy block:

- Desktop width: 540 px.
- Mobile width: calc(100% - 32px).
- Align to the right content gutter.
- Place above the booking rail.

Exact content:

- Eyebrow: `הסרט הגדול של השבוע`
- H1: `ספיידרמן: יום חדש`
- Original title: `SPIDER-MAN: BRAND NEW DAY`
- Metadata: `פנטזיה  •  150 דקות  •  מותר לכל`
- Primary action: Play icon, `לצפייה בטריילר`
- Secondary action: `לפרטי הסרט`

The primary action opens `TrailerDialog`. The fixture trailer URL can load in an iframe only after the dialog opens. If the URL fails, show poster artwork and `הטריילר אינו זמין כרגע`.

Hero navigation:

- Show three small line indicators near the lower left on desktop and centered above the booking rail on mobile.
- The fixture contains one fully specified hero. Render one active indicator and two inactive decorative indicators without auto-rotation.
- Do not build an autoplay carousel.

### 10.2 Booking rail

Desktop:

- Width: min(1280 px, calc(100% - 64 px)).
- Minimum height: 112 px.
- Position: absolute, centered, 24 px above the hero bottom.
- Background: `--color-red-600`.
- Radius: 8 px.
- Shadow: `--shadow-elevated`.
- Internal layout: 180 px mode control, four equal fields, 168 px CTA.

Mobile:

- Position inside the bottom of the hero with 16 px side gutters.
- Two-column grid for cinema and date.
- Movie field spans both columns.
- Hide the format field behind `אפשרויות נוספות` until expanded.
- CTA spans both columns.
- Minimum touch target: 48 px.

Mode control:

- Segments: `לפי סרט` and `לפי מתחם`.
- Initial segment: `לפי סרט`.
- Switching modes changes field order and clears only values that conflict.

Mode `לפי סרט` field order:

1. Movie.
2. Cinema.
3. Date.
4. Format.

Mode `לפי מתחם` field order:

1. Cinema.
2. Date.
3. Movie.
4. Format.

CTA copy:

- Incomplete required fields: `בחרו סרט ומתחם` and disabled.
- Complete selection: `הציגו שעות`.

On submit, navigate to `/booking` with search parameters and show the matching screening list. Keep labels visible above selected values. Do not use placeholder text as the only label.

### 10.3 Now showing section

Section id: `now-showing`.

Header row:

- H2: `עכשיו בקולנוע`
- Tabs: `הכול`, `ילדים`, `VIP`, `בקרוב`
- Link: `לכל הסרטים`

Desktop movie layout:

- Six columns at 1280 px.
- Four columns at 900 to 1279 px.
- Use a responsive grid. Do not use a carousel.

Mobile movie layout:

- Two columns.
- Gap: 16 px.

Show the first six movies from the fixture after filtering. Each `MoviePosterCard` contains:

- 2:3 poster image.
- Optional top-right badge such as `חדש` or `מדובב`.
- Hebrew title.
- Genre and runtime.
- Earliest screening at the active cinema.
- Two upcoming time chips when available.

Poster hover on pointer devices:

- Move the image up 4 px over 180 ms.
- Reveal a bottom action strip with `לפרטים` and a red ticket icon button.
- Keep title and metadata stationary so the grid does not shift.

Card click opens the movie detail page. A showtime chip opens `/booking` with that screening selected.

### 10.4 Tonight by time

Use a full-width `--color-ink-850` band.

Header:

- H2: `הערב לפי שעה`
- Active cinema selector.
- Date chips for today and the next four days.

Content:

- Group screenings under time buckets: `עד 18:00`, `18:00–21:00`, `אחרי 21:00`.
- Each row shows movie title, language, format badge, runtime, and time chips.
- Show up to five movie rows with `לכל ההקרנות` below.

Mobile uses a stacked list. Keep movie name and metadata on one row, then place horizontally wrapping time chips below. Do not create a horizontally scrolling table.

### 10.5 Premium experiences band

Use one unframed full-width visual band with three equal columns on desktop and a stacked list on mobile.

Items:

- VIP: warm gold accent, auditorium or lounge image, `ערב שלם בכרטיס אחד`.
- PRIME: teal accent, reclining seat image, `כורסאות מפנקות במחיר רגיל`.
- ONYX: sky accent, LED auditorium image, `תמונה חדה על מסך LED 4K`.

Each item links to the matching anchor on `/experiences`. Image, title, one sentence, and arrow form the whole item. Do not place cards inside a parent card.

### 10.6 Locations section

H2: `המתחם שלכם`

Show the eight fixture locations in a two-column desktop list paired with one large active location image. Hover or focus on a location updates the image and short metadata without navigation. Click opens the location detail page.

Mobile shows the locations as full-width rows with city, experience badges, address, and arrow. Use the selected cinema first.

### 10.7 Service strip

Place a compact full-width strip before the footer:

- `בדיקה או ביטול הזמנה`
- `נגישות`
- `שאלות נפוצות`
- `צור קשר`

Use icons plus text. Each target is at least 48 px high.

## 11. Movies catalog

### 11.1 Page header

Use an unframed title band, not a hero.

- H1: `סרטים בסינמה סיטי`
- Supporting copy: `בחרו סרט, מתחם ושעה שמתאימים לכם.`
- Active cinema selector.

### 11.2 Filter bar

The filter bar remains sticky below the header on desktop. It scrolls with content on mobile.

Controls:

- Search field, label `חיפוש סרט`.
- Status segmented control: `עכשיו`, `בקרוב`, `הכול`.
- Genre menu.
- Language menu: `עברית`, `אנגלית`, `רוסית`, `צרפתית`.
- Experience menu: `רגיל`, `VIP`, `PRIME`, `ONYX`.
- Checkbox: `לילדים`.
- Sort menu: `הקרוב ביותר`, `א׳–ת׳`, `תאריך בכורה`.
- Text button: `ניקוי סינון`, visible only after a filter changes.

Use URL search parameters for filters. Refreshing and sharing the URL must preserve the visible result set.

### 11.3 Results

Use the poster grid from the homepage. Display result count above it:

`נמצאו {count} סרטים`

Empty state:

- Film icon.
- Title: `לא מצאנו סרטים בסינון הזה`
- Body: `נסו לבחור מתחם אחר או לנקות חלק מהמסננים.`
- Action: `ניקוי סינון`

Loading state uses poster-shaped skeletons with fixed 2:3 ratio. Skeletons must reserve final dimensions.

## 12. Movie detail page

### 12.1 Hero

Use a full-bleed backdrop with a solid dark overlay. Do not put the title in a floating card.

Desktop content:

- Poster at the right edge of the content grid, width 244 px, 2:3 ratio.
- Title and metadata to its left in the RTL flow.
- Showtime CTA group below metadata.

Mobile content:

- Backdrop height 260 px.
- Poster overlaps the lower edge by 72 px, width 116 px.
- Text starts beside the poster and continues full width below it.

Content:

- Hebrew H1.
- Original title.
- Genre, runtime, release date, age restriction.
- Language and subtitle badges.
- `לצפייה בטריילר` action.
- Synopsis with a three-line collapse on mobile and `לקריאת התקציר המלא` toggle.

If `photosensitivityWarning` is present, show an Info callout before showtimes:

Title: `מידע חשוב לפני הצפייה`

Use the fixture warning text. Use sky or teal, not danger red, unless the content describes a prohibited age.

### 12.2 Showtime finder

Use the booking rail visual language as a full-width content tool.

Controls:

- Cinema selector.
- Seven date chips.
- Format filter.

Group results by cinema when no active cinema exists. Group by experience and language when a cinema exists.

Each screening row shows:

- Format badge.
- Spoken language and subtitle language.
- Hall name.
- Time chips.

Time chip states:

- Available: border and paper text.
- Hover or focus: gold border and subtle gold background.
- Selected: gold background, ink text.
- Low availability: small `כמעט מלא` label.
- Sold out: disabled with `אזל` and a line through the time.

Clicking an available time opens `/booking` with the screening selected.

### 12.3 Related movies

Show four movies sharing genre or audience. Do not show the current movie. Use a simple poster grid with H2 `אולי תאהבו גם`.

## 13. Cinemas pages

### 13.1 Cinemas index

H1: `מתחמי סינמה סיטי`

Intro: `שמונה מתחמים, מאות הקרנות, וחוויה שמתאימה לכל ערב.`

Desktop uses a two-column list. Each `CinemaCard` is a 16:9 location image with HTML text over a solid dark caption band at the bottom. Show city, compact address, current open status, and experience badges.

Mobile uses one column.

Open status logic:

- Calculate against fixture weekly hours and the browser’s Asia/Jerusalem time.
- Copy: `פתוח עכשיו` in success green, `נפתח ב־{time}` in gold, or `סגור היום` in muted text.
- If hours cannot be parsed, omit the status instead of guessing.

### 13.2 Cinema detail

Hero:

- Full-bleed 16:6 location image.
- H1: `סינמה סיטי {city}`.
- Address and open status.
- Primary action: `להקרנות במתחם` scrolls to showtimes.
- Secondary action: Navigation icon, `ניווט` opens the fixture map URL in a new tab.

Information band:

- Today’s hours.
- Parking summary.
- Public transport summary.
- Available experiences.
- Accessibility summary.

Use icon-and-text rows. Avoid small cards around each fact.

Main content:

1. `מה מקרינים היום` with date chips and movie rows.
2. `מידע על המתחם` with full address and description.
3. `שעות פעילות` as a seven-row definition list.
4. `איך מגיעים` with driving and public transport text.
5. `מה יש במתחם` with amenity chips.

The mobile page keeps `להזמנת כרטיסים` as a sticky bottom button after the hero leaves the viewport. Hide it on the booking routes.

## 14. Experiences page

Route: `/experiences`

H1: `יותר מסרט`

Supporting copy: `בחרו את חוויית הצפייה שמתאימה לערב שלכם.`

Create three full-width sections with distinct image treatment and no enclosing cards.

### 14.1 VIP section

Anchor: `#vip`

- Eyebrow: `VIP`
- Heading: `ערב שלם, בכרטיס אחד`
- Body: explain lounge arrival, food and drink, age restriction, and reclining seats using fixture content.
- Facts row: locations, recommended arrival, age.
- CTA: `מצאו הקרנת VIP`.

Use warm gold accents and a lounge image.

### 14.2 PRIME section

Anchor: `#prime`

- Eyebrow: `CINEMA PRIME`
- Heading: `נוחות של VIP במחיר קולנוע רגיל`
- Body: use fixture content.
- Facts row: Netanya, Hadera, Kfar Saba.
- CTA: `מצאו הקרנת PRIME`.

Use teal accents and a reclining-seat image.

### 14.3 ONYX section

Anchor: `#onyx`

- Eyebrow: `ONYX 4K LED`
- Heading: `כל פרט נשאר חד`
- Body: explain the Glilot LED auditorium with fixture content.
- Facts row: Glilot, 4K LED, selected screenings.
- CTA: `להקרנות ONYX`.

Use sky accents and an auditorium image.

The CTA for each section opens `/movies` with the matching experience filter.

## 15. Booking flow

### 15.1 Shared behavior

The booking flow uses four visible steps:

1. `הקרנה`
2. `כרטיסים ומושבים`
3. `תשלום`
4. `אישור`

Desktop progress appears under the header. Mobile progress shows the current step and `שלב {n} מתוך 4`.

Store the draft under `cinemaCity.bookingDraft.v1`. A draft expires 15 minutes after seat selection starts. Display a countdown only on the seats and checkout pages.

The prototype does not lock real seats. The countdown communicates the intended production behavior.

When a draft expires:

- Disable checkout.
- Clear selected seats.
- Show modal title `הזמן לבחירת המושבים הסתיים`.
- Body: `כדי להציג זמינות עדכנית, בחרו שוב הקרנה ומושבים.`
- Action: `חזרה לבחירת הקרנה`.

Route guards:

- `/booking/seats` requires a screening.
- `/booking/checkout` requires a screening, ticket count, and matching number of seats.
- `/booking/confirmation` requires a completed fixture order in session storage.
- Invalid access redirects to the earliest valid step and shows a toast.

### 15.2 Step 1: screening

Route: `/booking`

H1: `בוחרים הקרנה`

Desktop layout:

- Main column: 2fr.
- Sticky order summary: 1fr, maximum width 360 px.

Selection controls:

- Movie combobox.
- Cinema combobox.
- Seven date chips.
- Experience filters.
- Grouped screening times.

Pre-fill from URL search parameters or a valid draft. If no values exist, use the active cinema and no movie.

The continue button copy is `המשך לכרטיסים ומושבים`. Enable it after a screening is selected.

### 15.3 Step 2: tickets and seats

Route: `/booking/seats`

H1: `בוחרים כרטיסים ומושבים`

#### Ticket quantities

Show ticket types from the selected screening. Each row contains name, optional note, formatted price, minus button, quantity, plus button, and line total.

Rules:

- Minimum total tickets: 1.
- Maximum total tickets: 8.
- Quantity never drops below 0.
- Disable plus buttons after total reaches 8.
- Show inline error if the user tries to continue with no tickets.
- Ticket price uses `Intl.NumberFormat('he-IL', { style: 'currency', currency: 'ILS' })`.

#### Seat map

The seat map is a framed tool, not a decorative card.

Layout:

- Screen indicator at the top with copy `המסך`.
- Rows ordered from A near the screen to H at the back.
- Seat numbers increase right-to-left in the visual layout.
- A center aisle separates seats 5 and 6.
- The container can scroll horizontally on screens narrower than the map, but the page itself must not scroll horizontally.

Seat states:

- Available: dark fill, paper border.
- Selected: gold fill, ink seat number.
- Occupied: muted solid fill, disabled.
- Accessible: teal outline plus Accessibility icon.
- Companion: sky outline.
- Premium: small gold dot and label in legend.

Selection rules:

- Selected seat count must equal total ticket count before continuing.
- Clicking an available seat toggles it.
- Selecting more seats than tickets shows toast `בחרתם את מספר המושבים המרבי להזמנה זו`.
- Decreasing ticket count removes selected seats from the latest selected backward until counts match.
- If an accessible seat is selected, show information text about eligibility. Do not block selection in the prototype.
- Warn when a selection leaves one isolated available seat between occupied or selected seats. Do not block continuation.

Keyboard behavior:

- Every seat is a button with name `שורה {row}, מושב {number}, {state}`.
- Arrow keys move focus between neighboring seats.
- Enter and Space toggle an available seat.
- Home moves to the first seat in the row. End moves to the last.
- Disabled seats remain discoverable to screen readers but cannot receive normal tab focus.

Continue button:

- Copy: `המשך לתשלום`.
- Enable only when ticket and selected seat counts match and exceed zero.

### 15.4 Step 3: checkout

Route: `/booking/checkout`

H1: `פרטים ותשלום`

Desktop uses a 2fr form and a sticky 1fr order summary. Mobile places the summary in a collapsible panel above the form with label `סיכום הזמנה`.

Contact fields:

- Full name, required.
- Email, required and validated.
- Mobile phone, required. Accept Israeli formats with or without separators.

Mock payment fields:

- Payment method segmented control: `כרטיס אשראי לדוגמה`, `שובר לדוגמה`.
- The card option shows a notice, not card fields.
- Exact notice: `זהו אתר הדגמה. אין להזין פרטי אשראי אמיתיים. לחיצה על אישור תיצור הזמנה מדומה בלבד.`
- The voucher option shows one field labeled `קוד שובר לדוגמה`. Accept `DEMO20` and display a 20 ILS discount capped at the subtotal. Any other non-empty code shows `הקוד אינו מוכר בגרסת ההדגמה`.

Consent:

- Required checkbox: `קראתי ואני מאשר/ת את תנאי הרכישה ואת מדיניות הביטולים.`
- Optional checkbox: `אשמח לקבל עדכונים והטבות מסינמה סיטי.`

Order summary:

- Movie and original title.
- Cinema and hall.
- Local date and time.
- Ticket lines.
- Seat labels.
- Service fee.
- Discount, if present.
- Total.

Confirmation button:

- Copy: `אישור הזמנה מדומה • {formattedTotal}`.
- Disable until required fields and consent pass validation.
- On click, wait 700 ms, create a fixture order, clear the draft, store the order in session storage, and navigate to confirmation.
- Prevent double submission.

### 15.5 Step 4: confirmation

Route: `/booking/confirmation`

Use a focused confirmation layout with no marketing sections.

Content:

- Animated check mark that respects reduced motion.
- H1: `הכרטיסים שלכם מוכנים`
- Body: `שלחנו את פרטי ההזמנה לכתובת שהזנתם. בגרסת ההדגמה לא נשלח מייל בפועל.`
- Order reference in large copyable text.
- Movie poster thumbnail.
- Cinema, date, time, hall, tickets, seats, and total.
- Mock QR graphic built with CSS grid or a local generated bitmap. Add accessible text `קוד כניסה מדומה`.

Actions:

- Primary: `חזרה לעמוד הבית`.
- Secondary: `ניהול ההזמנה`.
- Icon button: `העתקת מספר הזמנה`, with success toast.

Do not show confetti.

## 16. Manage order

Route: `/manage-order`

H1: `בדיקה או ביטול הזמנה`

Fields:

- Order reference.
- Email.

Fixture success credentials:

- Reference: `CC-482731`
- Email: `demo@cinemacity.co.il`

Success state shows the order, a `ביטול הזמנה` danger text button, and a `חזרה לסרטים` link.

Cancellation behavior:

- Open a confirmation dialog.
- Title: `לבטל את ההזמנה?`
- Body: `הפעולה תשנה את סטטוס ההזמנה בדפדפן הזה. לא יתבצע זיכוי אמיתי.`
- Cancel action: `השאירו את ההזמנה`.
- Confirm action: `ביטול הזמנה מדומה`.
- On confirm, change status to `cancelled`, disable the button, and show `ההזמנה בוטלה בגרסת ההדגמה`.

Failure copy:

`לא מצאנו הזמנה שתואמת לפרטים. בדקו את מספר ההזמנה ואת כתובת המייל.`

Do not reveal whether the reference or email failed separately.

## 17. Search dialog

Open from the header search button. Use a centered desktop dialog and full-screen mobile dialog.

Behavior:

- Focus the input on open.
- Label: `חיפוש באתר`.
- Placeholder: `חפשו סרט או מתחם`.
- Search after two characters.
- Match Hebrew title, original title, genre, and cinema city.
- Show at most five movies and three cinemas.
- Highlight no substring with raw HTML. Use React text segments.
- Arrow keys move through results. Enter opens the active result.
- Escape closes and returns focus to the search button.

Initial state shows:

- `חיפושים מהירים`
- Links: `סרטי ילדים`, `VIP`, `הקרנות הערב`, `סינמה סיטי גלילות`.

No results:

`לא מצאנו תוצאה ל״{query}״`

## 18. Reusable component contracts

### 18.1 Button

Variants: `primary`, `secondary`, `ghost`, `danger`, `icon`.

Sizes:

- Standard: 48 px high.
- Compact: 40 px high.
- Icon: 44 x 44 px desktop, 48 x 48 px mobile.

Required states: default, hover, active, focus-visible, disabled, loading.

The loading state keeps the original width and uses a spinner plus `טוען…` where space allows.

### 18.2 SelectField

Use a native `select` when the option count stays below 20. Keep a visible label. Show validation below the field without changing field height.

### 18.3 SegmentedControl

Use buttons with `role="tablist"` only when the control switches visible content. Use radio inputs for form choices. Arrow keys change the active item.

### 18.4 ShowtimeChip

Fixed dimensions: minimum 68 x 44 px. The time uses Latin digits inside an element with `dir="ltr"`. Add labels outside the chip for sold-out and low-availability states so chip width does not jump.

### 18.5 StatusBadge

Badges may display format, language, audience, or availability. Use 4 px radius, 12 px horizontal padding, 28 px minimum height. Do not use badges as buttons unless the component renders a real button.

### 18.6 OrderSummary

Use a semantic `<aside>` with heading `סיכום הזמנה`. It must expose the same data on seats and checkout pages. Totals update without layout shift. Announce total changes in a polite live region.

### 18.7 Dialogs and drawers

All overlays must:

- Trap focus.
- Close on Escape unless submission is pending.
- Restore focus to the trigger.
- Use `aria-modal="true"` and an accessible heading.
- Prevent background scroll.
- Keep close buttons at least 48 x 48 px on mobile.

## 19. Responsive behavior

### 19.1 Breakpoints

```css
/* Mobile: default, 0-767 px */
@media (min-width: 768px) { /* Tablet */ }
@media (min-width: 1100px) { /* Desktop */ }
@media (min-width: 1440px) { /* Wide desktop */ }
```

Do not add component-specific arbitrary breakpoints unless text overlap proves one necessary.

### 19.2 Mobile requirements

- One primary column.
- Two-column poster grid.
- 16 px page gutters.
- Mobile drawer navigation.
- Booking rail forms a compact grid inside the hero.
- Sticky bottom CTA on movie and cinema detail pages.
- Booking order summary collapses above the form.
- Seat map scrolls inside its own container.
- Footer columns become accordion sections with semantic buttons.

### 19.3 Tablet requirements

- Four-column poster grid when width allows.
- Desktop header may remain until 1099 px only if all labels fit; otherwise use mobile header.
- Booking form uses one main column and summary below at 768 to 899 px, then two columns at 900 px.

### 19.4 Wide desktop requirements

- Content stays within 1280 px.
- Hero artwork remains full bleed.
- Do not increase font sizes beyond the token table.
- Additional width becomes side breathing room, not oversized cards.

### 19.5 Required viewport tests

Verify at:

- 360 x 800
- 390 x 844
- 768 x 1024
- 1280 x 720
- 1440 x 900
- 1920 x 1080

At every viewport:

- No text overlaps another element.
- No button label clips.
- No page-level horizontal scroll.
- The homepage shows a hint of the next section in the first viewport.
- Booking controls remain usable.
- The cookie banner does not hide required actions.

## 20. RTL and localization rules

- Set direction on the document, not per page.
- Use CSS logical properties such as `margin-inline-start` and `inset-inline-end`.
- Keep times, phone numbers, order references, prices, and original English titles in isolated `dir="ltr"` spans.
- Use `Intl.DateTimeFormat('he-IL')` for dates.
- Use `Intl.NumberFormat('he-IL')` for prices.
- Show day names in Hebrew.
- Chevron meaning follows navigation direction. A link that visually moves deeper into content points left in RTL.
- Do not reverse seat row letters or numeric values. Reverse only their visual ordering in the grid.
- Test mixed Hebrew and English titles for punctuation placement.

## 21. Accessibility

Target WCAG 2.2 AA.

Required behavior:

- All interactive elements work by keyboard.
- Focus indicators use a 2 px gold outline with 3 px offset and remain visible against red and dark surfaces.
- Body text contrast reaches 4.5:1. Large text and UI boundaries reach applicable AA ratios.
- Touch targets measure at least 44 x 44 px, and 48 x 48 px on primary mobile controls.
- Every form field has a persistent label and linked error text.
- Validation moves focus to the first invalid field after submit.
- Dynamic errors use `role="alert"`.
- Toasts use one polite live region and never steal focus.
- Images use meaningful Hebrew alt text. Decorative texture uses empty alt or CSS background.
- Trailer iframe has a title.
- The page restores focus after dialog close.
- Route changes move focus to the page H1 and update the document title.
- `prefers-reduced-motion: reduce` removes entrance translations, route transitions, parallax, and animated check marks.
- `prefers-contrast: more` strengthens borders and removes low-opacity text.
- Accessible seats remain visible without relying on color. Include an icon or pattern.
- Photosensitivity warnings appear before trailer and screening actions.
- Age restrictions appear beside the title and again before checkout for 16+ and 18+ content.

Run an automated accessibility scan on the home, movie detail, seats, checkout, and manage-order success pages. Automated scans do not replace keyboard testing.

## 22. Motion

Use motion to establish rhythm, not to decorate every control.

### 22.1 Page entry

Homepage only:

- Header fades from 0 to 1 over 250 ms.
- Hero copy moves 12 px upward while fading over 420 ms.
- Booking rail follows after 100 ms over 380 ms.
- First poster row staggers by 45 ms per item when it first enters the viewport.

### 22.2 Interactions

- Buttons: 140 ms color and border transition.
- Poster image hover: 180 ms transform.
- Dialog: 180 ms opacity and 8 px scale.
- Mobile drawer: 220 ms transform.
- Selected seat: 120 ms scale from 0.94 to 1.

Do not use looping animation, autoplay hero transitions, cursor effects, bouncing CTAs, scroll-jacking, or long parallax.

## 23. State and persistence

Use these keys:

```text
cinemaCity.activeCinema.v1
cinemaCity.bookingDraft.v1
cinemaCity.cookieConsent.v1
cinemaCity.cancelledOrders.v1
```

Rules:

- Active cinema persists until changed.
- Default active cinema is `glilot` when no stored value exists.
- Booking draft persists across refresh until completed, cleared, or expired.
- Do not persist contact fields after confirmation.
- Store the generated confirmation order in `sessionStorage`, not local storage.
- Parse stored values defensively. Invalid JSON returns to defaults without crashing.
- Fixture cancellation persists in the current browser so repeated lookup shows the cancelled state.

## 24. Data model

Use these TypeScript shapes. The implementation may add derived view models but must not remove required fields.

```ts
export type Experience = 'standard' | 'vip' | 'prime' | 'onyx';
export type Availability = 'available' | 'low' | 'sold-out';
export type MovieStatus = 'now-showing' | 'coming-soon';

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
```

## 25. Assets

### 25.1 Asset policy

- Serve all runtime images locally from `public/images`.
- Use WebP or AVIF for photos when supported by the source workflow.
- Keep the logo transparent.
- Provide width and height attributes for every image.
- Use `object-fit: cover` for backdrops and location photos.
- Use `object-fit: contain` only for the logo.
- Poster aspect ratio is 2:3.
- Location image aspect ratio is 16:9.
- Hero backdrop target is 1920 x 800 or larger.
- Compress poster files below 180 KB and hero images below 550 KB when visual quality allows.

### 25.2 Source handling

`fixture-data.json` contains official-site image URLs as source references. The implementation model must download those assets into the local folders and replace runtime fixture URLs with local paths. Keep a `public/images/SOURCES.md` file that maps each local file to its source URL and research date.

Keep the copied fixture file unchanged. Create `src/data/assetManifest.ts` that maps each movie and cinema ID to its local poster, backdrop, or location path. `FixtureCinemaRepository` combines the fixture record with this manifest and returns the runtime `posterUrl`, `backdropUrl`, and `imageUrl` fields from section 24. A missing manifest entry uses the designed fallback block.

Generate individual `Seat` records in the repository from each `SeatMapDefinition`. A seat ID combines its row and number, such as `F7`. Apply kind precedence in this order: accessible, companion, premium, standard. Apply occupied status after kind. This keeps the fixture compact while giving `SeatMap` a normalized array.

Use these filenames:

```text
brand/cinema-city-logo.png
heroes/spider-man-brand-new-day.webp
posters/spider-man-brand-new-day.webp
posters/spa-weekend.webp
posters/mutiny.webp
posters/coyote-vs-acme-he.webp
posters/insidious-out-of-the-further.webp
posters/la-la-land-10.webp
posters/pout-pout-fish-he.webp
posters/the-odyssey.webp
locations/glilot.webp
locations/rishon-lezion.webp
locations/jerusalem.webp
locations/kfar-saba.webp
locations/netanya.webp
locations/hadera.webp
locations/beer-sheva.webp
locations/ashdod.webp
experiences/vip.webp
experiences/prime.webp
experiences/onyx.webp
texture/film-grain.webp
```

If an image download fails, create a clearly designed fallback block that uses the movie title, genre, and one accent color. Do not show a broken image icon or unrelated stock image.

## 26. Loading, errors, and empty states

### 26.1 App load

Render the header and page background at once. Use fixed-dimension skeletons for data areas. Do not use a full-screen spinner.

### 26.2 Repository error

Use `ErrorState` with:

- Title: `משהו השתבש בהקרנת העמוד`
- Body: `לא הצלחנו לטעון את המידע. נסו שוב.`
- Action: `ניסיון נוסף`

Keep the header and footer usable.

### 26.3 Offline

Listen to the browser online state. Show a non-blocking top banner:

`אין כרגע חיבור לרשת. אפשר להמשיך לעיין במידע שכבר נטען.`

The fixture prototype still works. Keep the message to model production behavior.

### 26.4 Missing route record

Movie or cinema slug not found:

- H1: `העמוד לא נמצא`
- Body: `יכול להיות שהקישור השתנה או שהתוכן כבר אינו זמין.`
- Actions: `לכל הסרטים`, `לעמוד הבית`.

## 27. SEO and metadata

Update title and description per route.

Examples:

- Home title: `סינמה סיטי | סרטים, הקרנות והזמנת כרטיסים`
- Movies title: `סרטים עכשיו בקולנוע | סינמה סיטי`
- Movie title: `{titleHe} | הקרנות וכרטיסים | סינמה סיטי`
- Cinema title: `סינמה סיטי {cityHe} | שעות והקרנות`

Add:

- Canonical placeholders using `https://www.cinema-city.co.il` only in production configuration.
- Open Graph title, description, and image.
- JSON-LD `Movie` data on movie pages.
- JSON-LD `MovieTheater` data on cinema pages.
- Descriptive Hebrew meta descriptions under 160 characters.

The prototype must not claim that fixture availability or prices are live.

## 28. Analytics contract

Create an `analytics.ts` adapter that logs events to the console only in development. Components call the adapter rather than `console.log`.

Required events:

```text
cinema_selected
movie_opened
movie_filter_changed
search_opened
search_result_selected
showtime_selected
booking_started
ticket_quantity_changed
seat_selected
seat_deselected
checkout_viewed
voucher_applied
demo_order_confirmed
manage_order_lookup
demo_order_cancelled
cookie_consent_updated
```

Each event includes only relevant IDs and UI context. Do not log names, email, phone, or free-form search after checkout begins.

## 29. Performance

Targets on a mid-range mobile profile:

- Lighthouse performance score: 85 or higher for the fixture build.
- Accessibility score: 95 or higher.
- Largest Contentful Paint: under 2.5 seconds on a local production build with throttling.
- Cumulative Layout Shift: under 0.1.
- Initial JavaScript gzip: target under 220 KB.

Implementation rules:

- Lazy-load route modules after the homepage.
- Preload the hero image and two font files.
- Lazy-load below-fold posters and location images.
- Reserve image dimensions.
- Load the trailer iframe only after interaction.
- Avoid large animation libraries beyond `motion`.
- Do not ship source image files larger than needed.

## 30. Testing

### 30.1 Unit tests

Cover:

- Movie filtering by query, status, language, audience, and experience.
- Screening grouping by date and experience.
- Price calculation with service fee and `DEMO20` discount.
- Draft expiration.
- Open-status calculation in Asia/Jerusalem.
- Stored-state fallback after invalid JSON.
- Seat count enforcement when ticket quantity changes.

### 30.2 Component tests

Cover:

- BookingRail disabled and enabled states.
- MoviePosterCard title and showtime actions.
- SearchDialog keyboard navigation.
- TicketQuantity min and max behavior.
- SeatMap keyboard selection.
- Checkout validation and double-submit prevention.
- CookieBanner persistence.
- Manage-order generic failure response.

### 30.3 End-to-end tests

Required flow 1, desktop:

1. Open `/` at 1280 x 720.
2. Confirm the logo, hero, booking rail, and now-showing hint are visible.
3. Select Spider-Man, Glilot, 21 August, standard.
4. Select the 20:30 screening.
5. Add two adult tickets.
6. Select two adjacent seats.
7. Enter demo contact details.
8. Accept purchase terms.
9. Confirm the demo order.
10. Assert confirmation reference and seats appear.

Required flow 2, mobile:

1. Open `/movies` at 390 x 844.
2. Enable the children filter.
3. Open Coyote vs. Acme Hebrew.
4. Choose a screening.
5. Verify no horizontal page scroll through checkout.

Required flow 3, management:

1. Open `/manage-order`.
2. Look up `CC-482731` and `demo@cinemacity.co.il`.
3. Confirm the fixture order renders.
4. Cancel it.
5. Refresh and confirm the cancelled state remains.

### 30.4 Visual checks

Capture screenshots at all required viewport sizes for:

- Homepage.
- Movies catalog with filters active.
- Movie detail.
- Seat selection.
- Checkout.
- Confirmation.

Inspect screenshots for clipping, overlap, unintended one-color dominance, incorrect RTL ordering, broken images, and layout shifts.

## 31. Acceptance checklist

The build is complete only when every item below passes.

### Product

- [ ] All routes in section 8 render and link to each other.
- [ ] The active cinema updates home, movie, and booking showtimes.
- [ ] Search finds movies and cinemas.
- [ ] Filters persist in URL parameters.
- [ ] A visitor can complete the full demo booking flow.
- [ ] The fixture order can be found and cancelled.

### Visual

- [ ] The homepage uses a full-bleed real movie backdrop.
- [ ] The Cinema City logo is prominent in the first viewport.
- [ ] The red booking rail appears on the hero and informs the booking flow.
- [ ] Poster artwork drives the catalog design.
- [ ] Sections use full-width bands or unframed layouts.
- [ ] Cards do not nest inside cards.
- [ ] Radius does not exceed 8 px except circular icon or seat shapes.
- [ ] Purple gradients, decorative orbs, and glass panels do not appear.

### Responsive

- [ ] All six viewport tests pass.
- [ ] The page has no horizontal scroll.
- [ ] Long Hebrew titles fit.
- [ ] Mobile sticky actions do not collide with cookie consent.
- [ ] Seat map scroll stays inside its own container.

### Accessibility

- [ ] Skip link works.
- [ ] Header, dialogs, search, filters, forms, and seat map work by keyboard.
- [ ] Focus remains visible.
- [ ] All pages contain one H1.
- [ ] Route changes update title and focus.
- [ ] Reduced-motion behavior works.
- [ ] Automated scans show no serious or critical issues.

### Engineering

- [ ] TypeScript strict build passes.
- [ ] Lint passes.
- [ ] Unit tests pass.
- [ ] Playwright tests pass.
- [ ] Runtime data goes through `CinemaRepository`.
- [ ] No real payment or private data leaves the browser.
- [ ] Production build starts and client-side route fallback works.

## 32. Build order for a smaller implementation model

Follow this sequence. Run the relevant check after each phase.

1. Scaffold Vite, React, TypeScript, routing, styles, and test setup.
2. Copy fixtures, define TypeScript types, and implement the fixture repository.
3. Build design tokens, fonts, reset, layout utilities, buttons, fields, badges, and dialogs.
4. Build the application shell, RTL behavior, header, mobile drawer, footer, and cookie banner.
5. Build movie, cinema, and showtime components with fixed responsive dimensions.
6. Build the homepage and verify all six viewports before continuing.
7. Build movies, movie detail, cinemas, cinema detail, and experiences.
8. Build booking context, draft persistence, route guards, and progress UI.
9. Build screening, tickets, seat map, checkout, and confirmation in that order.
10. Build search and manage-order flows.
11. Add loading, empty, error, offline, and expired-draft states.
12. Add unit, component, and end-to-end tests.
13. Run build, lint, tests, accessibility checks, and screenshot review.
14. Fix every acceptance failure before adding optional motion polish.

## 33. Final implementation handoff

The implementation model should return:

- The running local URL.
- A short list of completed routes.
- Test and build results.
- Screenshot paths for desktop and mobile homepage, seats, and checkout.
- Any fixture or production integration limitations.
- No redesign proposal and no list of features left as placeholders.
