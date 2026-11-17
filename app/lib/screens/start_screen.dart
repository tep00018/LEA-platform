import 'package:flutter/material.dart';

import '../theme/lea_colors.dart';
import '../widgets/lea_avatar.dart';

/// Shown for the moment it takes to check a saved login at start-up.
class StartScreen extends StatelessWidget {
  const StartScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: context.lea.bg,
      body: Center(
        child: Semantics(label: 'Opening LEA', child: const LeaAvatar(size: 56)),
      ),
    );
  }
}
