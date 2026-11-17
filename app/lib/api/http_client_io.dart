import 'package:http/http.dart' as http;

/// Android, iOS, desktop and `flutter test`: the default client streams responses.
http.Client createHttpClient() => http.Client();
