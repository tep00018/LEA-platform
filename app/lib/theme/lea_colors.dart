import 'package:flutter/material.dart';

/// LEA's Chalkboard colour tokens (docs/design/DESIGN.md, "Colour tokens").
///
/// Widgets read colours only from here (`context.lea`), never as literals.
@immutable
class LeaColors extends ThemeExtension<LeaColors> {
  const LeaColors({
    required this.bg,
    required this.surface,
    required this.surface2,
    required this.ink,
    required this.muted,
    required this.line,
    required this.primary,
    required this.onPrimary,
    required this.accent,
    required this.accentSoft,
    required this.success,
    required this.successSoft,
    required this.warning,
    required this.danger,
    required this.dangerSoft,
    required this.board,
    required this.onBoard,
    required this.chalk,
  });

  final Color bg;
  final Color surface;
  final Color surface2;
  final Color ink;
  final Color muted;
  final Color line;
  final Color primary;
  final Color onPrimary;
  final Color accent;
  final Color accentSoft;
  final Color success;
  final Color successSoft;
  final Color warning;
  final Color danger;
  final Color dangerSoft;
  final Color board;
  final Color onBoard;
  final Color chalk;

  static const light = LeaColors(
    bg: Color(0xFFF3F5F1),
    surface: Color(0xFFFFFFFF),
    surface2: Color(0xFFE2E9E0),
    ink: Color(0xFF1B2621),
    muted: Color(0xFF56655D),
    line: Color(0xFFD2DBD0),
    primary: Color(0xFF2E5A47),
    onPrimary: Color(0xFFFFFFFF),
    accent: Color(0xFFA98712),
    accentSoft: Color(0xFFF5ECC3),
    success: Color(0xFF256B42),
    successSoft: Color(0xFFDDEFE2),
    warning: Color(0xFF9A5F06),
    danger: Color(0xFFB03A2E),
    dangerSoft: Color(0xFFF7E0DC),
    board: Color(0xFF2E5A47),
    onBoard: Color(0xFFF3F5F1),
    chalk: Color(0xFFF0D35E),
  );

  static const dark = LeaColors(
    bg: Color(0xFF111814),
    surface: Color(0xFF18221D),
    surface2: Color(0xFF223129),
    ink: Color(0xFFE7EFE9),
    muted: Color(0xFF9DB0A5),
    line: Color(0xFF2A3B33),
    primary: Color(0xFF86C9A8),
    onPrimary: Color(0xFF0F1F17),
    accent: Color(0xFFF0D35E),
    accentSoft: Color(0xFF3A3418),
    success: Color(0xFF74CD99),
    successSoft: Color(0xFF1C3A28),
    warning: Color(0xFFF0B75A),
    danger: Color(0xFFF08D84),
    dangerSoft: Color(0xFF3F2220),
    board: Color(0xFF1C3A2E),
    onBoard: Color(0xFFE7EFE9),
    chalk: Color(0xFFF0D35E),
  );

  @override
  LeaColors copyWith({
    Color? bg,
    Color? surface,
    Color? surface2,
    Color? ink,
    Color? muted,
    Color? line,
    Color? primary,
    Color? onPrimary,
    Color? accent,
    Color? accentSoft,
    Color? success,
    Color? successSoft,
    Color? warning,
    Color? danger,
    Color? dangerSoft,
    Color? board,
    Color? onBoard,
    Color? chalk,
  }) {
    return LeaColors(
      bg: bg ?? this.bg,
      surface: surface ?? this.surface,
      surface2: surface2 ?? this.surface2,
      ink: ink ?? this.ink,
      muted: muted ?? this.muted,
      line: line ?? this.line,
      primary: primary ?? this.primary,
      onPrimary: onPrimary ?? this.onPrimary,
      accent: accent ?? this.accent,
      accentSoft: accentSoft ?? this.accentSoft,
      success: success ?? this.success,
      successSoft: successSoft ?? this.successSoft,
      warning: warning ?? this.warning,
      danger: danger ?? this.danger,
      dangerSoft: dangerSoft ?? this.dangerSoft,
      board: board ?? this.board,
      onBoard: onBoard ?? this.onBoard,
      chalk: chalk ?? this.chalk,
    );
  }

  @override
  LeaColors lerp(ThemeExtension<LeaColors>? other, double t) {
    if (other is! LeaColors) return this;
    Color l(Color a, Color b) => Color.lerp(a, b, t)!;
    return LeaColors(
      bg: l(bg, other.bg),
      surface: l(surface, other.surface),
      surface2: l(surface2, other.surface2),
      ink: l(ink, other.ink),
      muted: l(muted, other.muted),
      line: l(line, other.line),
      primary: l(primary, other.primary),
      onPrimary: l(onPrimary, other.onPrimary),
      accent: l(accent, other.accent),
      accentSoft: l(accentSoft, other.accentSoft),
      success: l(success, other.success),
      successSoft: l(successSoft, other.successSoft),
      warning: l(warning, other.warning),
      danger: l(danger, other.danger),
      dangerSoft: l(dangerSoft, other.dangerSoft),
      board: l(board, other.board),
      onBoard: l(onBoard, other.onBoard),
      chalk: l(chalk, other.chalk),
    );
  }
}

extension LeaColorsContext on BuildContext {
  LeaColors get lea => Theme.of(this).extension<LeaColors>()!;
}
