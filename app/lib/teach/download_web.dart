import 'dart:js_interop';
import 'dart:typed_data';

import 'package:web/web.dart' as web;

/// Only the stub records files; kept here so both libraries export the same names.
final savedFiles = <String, List<int>>{};

/// Saves [bytes] as a browser download called [name].
Future<void> saveBytes(String name, List<int> bytes, String mime) async {
  final blob = web.Blob([Uint8List.fromList(bytes).toJS].toJS, web.BlobPropertyBag(type: mime));
  final url = web.URL.createObjectURL(blob);
  final anchor = web.HTMLAnchorElement()
    ..href = url
    ..download = name;
  web.document.body?.append(anchor);
  anchor.click();
  anchor.remove();
  web.URL.revokeObjectURL(url);
}
