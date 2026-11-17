import 'package:fetch_client/fetch_client.dart';
import 'package:http/http.dart' as http;

/// Web: the Fetch API, so streamed replies arrive as they're written.
///
/// `RequestMode.cors` matters: fetch_client defaults to `no-cors`, which gives opaque
/// responses the app can't read from a different-origin API.
http.Client createHttpClient() => FetchClient(mode: RequestMode.cors);
