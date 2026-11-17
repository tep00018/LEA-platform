/// The platform's HTTP client, picked at compile time.
///
/// On web, `package:http`'s default client buffers the whole response, which would hold
/// back a streamed reply until it finished; the Fetch API client streams. Everywhere else
/// the default client already streams.
library;

export 'http_client_io.dart' if (dart.library.js_interop) 'http_client_web.dart';
