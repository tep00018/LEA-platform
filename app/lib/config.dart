/// Build-time settings, passed with `--dart-define`.
library;

/// Where the LEA API runs. The default is LEA's local API port (8100); a phone emulator
/// or a deployed build passes its own with `--dart-define=LEA_API_URL=...`.
const apiBaseUrl = String.fromEnvironment('LEA_API_URL', defaultValue: 'http://127.0.0.1:8100');
