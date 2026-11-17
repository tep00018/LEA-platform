import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app.dart';
import 'providers.dart';

void main() {
  runApp(const ProviderScope(retry: noRetry, child: LeaApp()));
}
