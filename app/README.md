# LEA Flutter app (`lea_app`)

The LEA client for web (first) and mobile, built against the API in `docs/api/openapi.json`
to the design in `docs/design/`. How to run it: `docs/SETUP.md`, "The Flutter app (web)".

- `lib/api/`: API client, error type, SSE parser, models (checked against the spec by
  `test/api/models_spec_test.dart`), and the platform HTTP client (`fetch_client` on web,
  the default client elsewhere, chosen by conditional import).
- `lib/auth/`: token storage and the login state.
- `lib/theme/`: Chalkboard colour tokens (`context.lea`) and the type scale.
- `lib/shell/`: the responsive shell: rail and tabs at 720 px and wider, top bar and
  bottom navigation below.
- `lib/screens/`: screens by mode.
- `tool/render_screens_test.dart`: renders screens at the design's sizes for comparison.
