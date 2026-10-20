# Astana Walk interface

Mode: Operate. Inherit AFM's map/list/chat workflow and adapt its content to walking recommendations.
Desktop: narrow explorer, large interactive map, assistant pane. Mobile: explicit places/map/assistant navigation.
Surfaces: map-app look in the spirit of 2GIS (own branding, no 2GIS marks): grey canvas, white panels with soft shadows, green primary actions (#11821f), blue links, orange rating stars, round white map controls. Header: logo, pill stats (city + places, weather icon from the WMO code), Afisha pill, theme and language toggles. Explorer: grey search field with icon, quick category chips (one tap searches), compact place cards with walking time. Category colours appear on map pins, chips and list dots. Overrides live in `frontend/src/map-app.css`, loaded after `style.css`.
Typography: self-hosted Inter (Latin, Cyrillic, Kazakh glyphs), no font CDN, so the demo renders offline. Nothing below 11px; facts separated from uncertainty.
Themes: light and dark from design tokens in `frontend/src/tokens.css` (`[data-theme]`), chosen before first paint from the saved choice or the system setting; the OSM raster is dimmed in dark mode.
Language: every UI string goes through `useT()` with ru/kk keys in `frontend/src/lib/i18n.ts`; `npm run build` fails on missing translations or hard-coded Cyrillic JSX text (`scripts/validate-i18n.mjs`). Data text from the backend (place names, warnings, model answers) stays as published.
Structure (after AFM): `useWalk.ts` holds state and API actions; `components/` render TopBar, Explorer, MapPanel/PlaceSheet, Assistant and overlays; `lib/` has prefs, i18n, format, Icon (Lucide sprite), BackendStatus banner and ErrorBoundary per panel.
Accessibility: `tests/a11y.spec.ts` runs axe (WCAG 2.1 A/AA) for light/dark × ru/kk × desktop/mobile, including an open place card.
Core interaction: selecting a result reveals its route and sourced card; choosing up to three places enables comparison and a sequential itinerary.
Loading, empty, network/model failure and unknown data are explicit. Geolocation occurs only on button activation. Route snap caveats remain visible.
