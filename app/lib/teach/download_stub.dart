/// Outside the browser (tests), downloads are recorded instead of saved.
final savedFiles = <String, List<int>>{};

Future<void> saveBytes(String name, List<int> bytes, String mime) async {
  savedFiles[name] = bytes;
}
