import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'router.dart';
import 'theme/lea_theme.dart';

class LeaApp extends ConsumerWidget {
  const LeaApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return MaterialApp.router(
      title: 'LEA',
      debugShowCheckedModeBanner: false,
      theme: LeaTheme.light(),
      darkTheme: LeaTheme.dark(),
      themeMode: ThemeMode.system,
      routerConfig: ref.watch(routerProvider),
    );
  }
}
