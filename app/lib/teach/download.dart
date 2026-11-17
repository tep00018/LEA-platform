/// Saving a file the API returned (the KC spreadsheet): a browser download on the web.
library;

export 'download_stub.dart' if (dart.library.js_interop) 'download_web.dart';
