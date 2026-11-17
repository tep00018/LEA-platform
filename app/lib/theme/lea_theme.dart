import 'package:flutter/material.dart';

import 'lea_colors.dart';
import 'lea_type.dart';

/// Material 3 themes built from the Chalkboard tokens. Light and dark follow the system.
abstract final class LeaTheme {
  static ThemeData light() => _build(LeaColors.light, Brightness.light);
  static ThemeData dark() => _build(LeaColors.dark, Brightness.dark);

  static ThemeData _build(LeaColors c, Brightness brightness) {
    final scheme = ColorScheme(
      brightness: brightness,
      primary: c.primary,
      onPrimary: c.onPrimary,
      secondary: c.accent,
      onSecondary: c.ink,
      tertiary: c.accent,
      onTertiary: c.ink,
      error: c.danger,
      onError: c.surface,
      errorContainer: c.dangerSoft,
      onErrorContainer: c.ink,
      surface: c.surface,
      onSurface: c.ink,
      onSurfaceVariant: c.muted,
      surfaceContainerLowest: c.surface,
      surfaceContainerLow: c.surface,
      surfaceContainer: c.surface,
      surfaceContainerHigh: c.surface2,
      surfaceContainerHighest: c.surface2,
      outline: c.line,
      outlineVariant: c.line,
      inverseSurface: c.ink,
      onInverseSurface: c.bg,
      shadow: Colors.black,
      scrim: Colors.black,
    );

    final base = ThemeData(
      useMaterial3: true,
      brightness: brightness,
      colorScheme: scheme,
      fontFamily: LeaType.body,
      fontFamilyFallback: LeaType.fallback,
    );

    return base.copyWith(
      extensions: [c],
      scaffoldBackgroundColor: c.bg,
      canvasColor: c.bg,
      dividerColor: c.line,
      textTheme: _withWeightAxis(base.textTheme.apply(bodyColor: c.ink, displayColor: c.ink)),
      focusColor: c.primary.withValues(alpha: 0.12),
      textSelectionTheme: TextSelectionThemeData(
        cursorColor: c.primary,
        selectionColor: c.primary.withValues(alpha: 0.25),
        selectionHandleColor: c.primary,
      ),
      bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: c.surface,
        modalBackgroundColor: c.surface,
        surfaceTintColor: Colors.transparent,
        shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(16))),
      ),
      // Inputs: 1.5 px `line` border, radius 10, `surface` fill; focused: `primary` border.
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: c.surface,
        contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
        hintStyle: LeaType.ui(14).copyWith(color: c.muted),
        labelStyle: LeaType.ui(13, weight: FontWeight.w500).copyWith(color: c.ink),
        floatingLabelStyle: LeaType.ui(13, weight: FontWeight.w500).copyWith(color: c.ink),
        border: _inputBorder(c.line),
        enabledBorder: _inputBorder(c.line),
        focusedBorder: _inputBorder(c.primary),
        errorBorder: _inputBorder(c.danger),
        focusedErrorBorder: _inputBorder(c.danger),
        disabledBorder: _inputBorder(c.line),
      ),
      // Primary buttons: `primary` fill, radius 9, 600 weight.
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: c.primary,
          foregroundColor: c.onPrimary,
          disabledBackgroundColor: c.primary.withValues(alpha: 0.45),
          disabledForegroundColor: c.onPrimary,
          minimumSize: const Size(0, 42),
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 10),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(9)),
          textStyle: LeaType.ui(14, weight: FontWeight.w600),
        ).copyWith(side: _focusRing(c.ink)),
      ),
      // Keyboard focus shows a 2 px ring (DESIGN.md, "Accessibility"). On a primary-filled
      // button a primary ring would vanish, so filled buttons use ink.
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: ButtonStyle(
          side: WidgetStateProperty.resolveWith(
            (states) => BorderSide(
              color: states.contains(WidgetState.focused) ? c.primary : c.line,
              width: states.contains(WidgetState.focused) ? 2 : 1.5,
            ),
          ),
        ),
      ),
      textButtonTheme: TextButtonThemeData(style: ButtonStyle(side: _focusRing(c.primary))),
      snackBarTheme: SnackBarThemeData(
        backgroundColor: c.ink,
        contentTextStyle: LeaType.small().copyWith(color: c.bg),
        behavior: SnackBarBehavior.floating,
      ),
    );
  }

  static WidgetStateProperty<BorderSide?> _focusRing(Color color) => WidgetStateProperty.resolveWith(
    (states) => states.contains(WidgetState.focused) ? BorderSide(color: color, width: 2) : null,
  );

  static OutlineInputBorder _inputBorder(Color color) => OutlineInputBorder(
    borderRadius: BorderRadius.circular(10),
    borderSide: BorderSide(color: color, width: 1.5),
  );

  /// Material's built-in text styles only set `fontWeight`; add the matching `wght` axis
  /// so the bundled variable fonts render at the right weight.
  static TextTheme _withWeightAxis(TextTheme t) {
    TextStyle? fix(TextStyle? s) {
      if (s == null) return null;
      final w = (s.fontWeight ?? FontWeight.w400).value.toDouble();
      return s.copyWith(fontVariations: [FontVariation.weight(w)]);
    }

    return t.copyWith(
      displayLarge: fix(t.displayLarge),
      displayMedium: fix(t.displayMedium),
      displaySmall: fix(t.displaySmall),
      headlineLarge: fix(t.headlineLarge),
      headlineMedium: fix(t.headlineMedium),
      headlineSmall: fix(t.headlineSmall),
      titleLarge: fix(t.titleLarge),
      titleMedium: fix(t.titleMedium),
      titleSmall: fix(t.titleSmall),
      bodyLarge: fix(t.bodyLarge),
      bodyMedium: fix(t.bodyMedium),
      bodySmall: fix(t.bodySmall),
      labelLarge: fix(t.labelLarge),
      labelMedium: fix(t.labelMedium),
      labelSmall: fix(t.labelSmall),
    );
  }
}
