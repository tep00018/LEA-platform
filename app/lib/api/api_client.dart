import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'api_error.dart';
import 'sse.dart';

/// Talks to the LEA API: JSON requests with the bearer token, and streamed replies.
///
/// Every failure is thrown as an [ApiError]. When a request that carried the token gets
/// a 401, [onUnauthorized] runs first, so the app can clear the token and go to login.
/// [onReachability] hears whether each request reached the server (for the offline banner).
///
/// While a teacher previews a course as a student, [previewToken] returns the sandbox
/// account's token: student endpoints use it, `/teach` and `/admin` (and logging out) keep
/// the teacher's own token, and a 401 on the sandbox token calls [onPreviewUnauthorized]
/// (the preview ended) instead of logging the teacher out.
class ApiClient {
  ApiClient({
    required this.baseUrl,
    required http.Client httpClient,
    required this._token,
    this._onUnauthorized,
    this._onReachability,
    this._previewToken,
    this._onPreviewUnauthorized,
  }) : _http = httpClient;

  final String baseUrl;
  final http.Client _http;
  final String? Function() _token;
  final void Function()? _onUnauthorized;
  final void Function(bool reachable)? _onReachability;
  final String? Function()? _previewToken;
  final void Function()? _onPreviewUnauthorized;

  /// Paths that always use the teacher's (or student's) own login.
  static bool isStaffPath(String path) =>
      path.startsWith('/teach') || path.startsWith('/admin') || path == '/auth/logout';

  String? _tokenFor(String path) {
    final preview = _previewToken?.call();
    return preview != null && !isStaffPath(path) ? preview : _token();
  }

  Uri uri(String path, [Map<String, String>? query]) {
    final base = baseUrl.endsWith('/') ? baseUrl.substring(0, baseUrl.length - 1) : baseUrl;
    return Uri.parse('$base$path').replace(queryParameters: (query == null || query.isEmpty) ? null : query);
  }

  /// `GET`; [token] overrides the stored one (used to check a saved token at start-up).
  Future<Object?> get(String path, {Map<String, String>? query, String? token}) =>
      _send('GET', path, query: query, token: token);

  Future<Object?> post(String path, [Object? body]) => _send('POST', path, body: body);

  Future<Object?> delete(String path) => _send('DELETE', path);

  Future<Object?> put(String path, [Object? body]) => _send('PUT', path, body: body);

  /// `PATCH` that must return a JSON object.
  Future<Map<String, dynamic>> patchObject(String path, [Object? body]) async =>
      _object(await _send('PATCH', path, body: body));

  /// `PUT` that must return a JSON object.
  Future<Map<String, dynamic>> putObject(String path, [Object? body]) async => _object(await put(path, body));

  /// A multipart `POST` of [files] (`field`, file name, bytes) and text [fields].
  Future<Object?> postFiles(String path, List<(String, String, List<int>)> files, [Map<String, String>? fields]) async {
    final sentToken = _tokenFor(path);
    final request = http.MultipartRequest('POST', uri(path))
      ..headers.addAll(_headers(sentToken, json: false))
      ..fields.addAll(fields ?? const {});
    for (final (field, name, bytes) in files) {
      request.files.add(http.MultipartFile.fromBytes(field, bytes, filename: name));
    }
    final http.Response response;
    try {
      response = await http.Response.fromStream(await _http.send(request));
    } catch (_) {
      _onReachability?.call(false);
      throw ApiError.unreachable();
    }
    _onReachability?.call(true);
    return _decode(response, sentToken);
  }

  /// `GET` of a file (the KC spreadsheet); returns its bytes.
  Future<List<int>> getBytes(String path) async {
    final sentToken = _tokenFor(path);
    final http.Response response;
    try {
      response = await http.Response.fromStream(
        await _http.send(http.Request('GET', uri(path))..headers.addAll(_headers(sentToken, json: false))),
      );
    } catch (_) {
      _onReachability?.call(false);
      throw ApiError.unreachable();
    }
    _onReachability?.call(true);
    if (response.statusCode >= 200 && response.statusCode < 300) return response.bodyBytes;
    final error = ApiError.fromResponse(response.statusCode, response.body, response.headers);
    _checkUnauthorized(error, sentToken);
    throw error;
  }

  /// `GET` that must return a JSON object.
  Future<Map<String, dynamic>> getObject(String path, {Map<String, String>? query, String? token}) async =>
      _object(await get(path, query: query, token: token));

  /// `POST` that must return a JSON object.
  Future<Map<String, dynamic>> postObject(String path, [Object? body]) async => _object(await post(path, body));

  /// `POST` to a streaming endpoint. The returned stream always ends with one
  /// [ReplyDone] or [ReplyFailed]; it never throws.
  Stream<ReplyEvent> postStream(String path, Object? body) async* {
    final sentToken = _tokenFor(path);
    final request = http.Request('POST', uri(path))
      ..headers.addAll(_headers(sentToken, json: true))
      ..headers['Accept'] = 'text/event-stream'
      ..body = jsonEncode(body ?? const {});

    final http.StreamedResponse response;
    try {
      response = await _http.send(request);
    } catch (_) {
      _onReachability?.call(false);
      yield ReplyFailed(ApiError.unreachable());
      return;
    }
    _onReachability?.call(true);

    if (response.statusCode < 200 || response.statusCode >= 300) {
      final String text;
      try {
        text = await response.stream.bytesToString();
      } catch (_) {
        yield ReplyFailed(ApiError.unreachable());
        return;
      }
      final error = ApiError.fromResponse(response.statusCode, text, response.headers);
      _checkUnauthorized(error, sentToken);
      yield ReplyFailed(error);
      return;
    }

    await for (final event in decodeReplyEvents(parseSse(response.stream))) {
      if (event is ReplyFailed) _checkUnauthorized(event.error, sentToken);
      yield event;
    }
  }

  Future<Object?> _send(String method, String path, {Map<String, String>? query, Object? body, String? token}) async {
    final sentToken = token ?? _tokenFor(path);
    final request = http.Request(method, uri(path, query))..headers.addAll(_headers(sentToken, json: body != null));
    if (body != null) request.body = jsonEncode(body);

    final http.Response response;
    try {
      response = await http.Response.fromStream(await _http.send(request));
    } catch (_) {
      _onReachability?.call(false);
      throw ApiError.unreachable();
    }
    _onReachability?.call(true);
    return _decode(response, token == null ? sentToken : null);
  }

  /// The JSON body of a 2xx answer, or the [ApiError] for any other. A 401 on a request
  /// that carried [sentToken] ends that session (or the preview).
  Object? _decode(http.Response response, String? sentToken) {
    if (response.statusCode >= 200 && response.statusCode < 300) {
      if (response.body.isEmpty) return null;
      try {
        return jsonDecode(utf8.decode(response.bodyBytes));
      } on FormatException {
        throw const ApiError(
          status: 0,
          code: 'InvalidResponse',
          detail: "LEA sent a reply the app couldn't read. Please try again.",
        );
      }
    }

    final error = ApiError.fromResponse(
      response.statusCode,
      utf8.decode(response.bodyBytes, allowMalformed: true),
      response.headers,
    );
    // An explicit token is a start-up check (passed here as null); its caller decides.
    _checkUnauthorized(error, sentToken);
    throw error;
  }

  /// A 401 on a request that carried a token means the session has ended. A 401 without
  /// one (a wrong password at login) is just an error to show.
  void _checkUnauthorized(ApiError error, String? sentToken) {
    if (!error.isUnauthorized || sentToken == null) return;
    if (sentToken == _previewToken?.call()) {
      _onPreviewUnauthorized?.call();
    } else {
      _onUnauthorized?.call();
    }
  }

  Map<String, String> _headers(String? token, {required bool json}) => {
    'Accept': 'application/json',
    if (json) 'Content-Type': 'application/json',
    if (token != null) 'Authorization': 'Bearer $token',
  };

  Map<String, dynamic> _object(Object? json) {
    if (json is Map<String, dynamic>) return json;
    throw const ApiError(
      status: 0,
      code: 'InvalidResponse',
      detail: "LEA sent a reply the app couldn't read. Please try again.",
    );
  }
}
