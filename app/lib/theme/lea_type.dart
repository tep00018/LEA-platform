import 'package:flutter/painting.dart';

/// LEA's type scale (docs/design/DESIGN.md, "Type").
///
/// Both fonts are bundled as variable fonts, so every style sets the `wght` axis
/// explicitly: `fontWeight` alone doesn't move a variable font's axis on every platform.
/// Styles carry no colour; widgets add one from `context.lea`.
abstract final class LeaType {
  static const body = 'Lexend';
  static const display = 'Bricolage Grotesque';
  static const fallback = <String>['Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial', 'sans-serif'];

  static const tabular = [FontFeature.tabularFigures()];

  /// A Lexend (body/UI) style.
  static TextStyle ui(double size, {FontWeight weight = FontWeight.w400, double? height, double? letterSpacing}) {
    return TextStyle(
      fontFamily: body,
      fontFamilyFallback: fallback,
      fontSize: size,
      fontWeight: weight,
      fontVariations: [FontVariation.weight(weight.value.toDouble())],
      height: height,
      letterSpacing: letterSpacing,
    );
  }

  /// A Bricolage Grotesque (display) style. Letter-spacing −1% on large sizes, and the
  /// optical-size axis follows the font size as it does in the browser.
  static TextStyle heading(double size, {FontWeight weight = FontWeight.w700, double? height, double? letterSpacing}) {
    return TextStyle(
      fontFamily: display,
      fontFamilyFallback: fallback,
      fontSize: size,
      fontWeight: weight,
      fontVariations: [
        FontVariation.weight(weight.value.toDouble()),
        FontVariation('opsz', size.clamp(12, 96).toDouble()),
      ],
      height: height,
      letterSpacing: letterSpacing ?? (size >= 20 ? -0.01 * size : null),
    );
  }

  /// Monospace for code: JetBrains Mono, bundled (OFL).
  static const monoFamily = 'JetBrains Mono';

  static TextStyle mono(double size) => TextStyle(
    fontFamily: monoFamily,
    fontFamilyFallback: const [body, ...fallback],
    fontSize: size,
    fontWeight: FontWeight.w400,
    fontVariations: const [FontVariation.weight(400)],
    height: 1.45,
  );

  /// Uppercase labels and kickers: 11–12 px, +8% letter-spacing.
  static TextStyle label(double size, {FontWeight weight = FontWeight.w400}) =>
      ui(size, weight: weight, letterSpacing: 0.08 * size);

  // Named sizes from the spec (desktop / phone where they differ).
  static TextStyle wordmark() => heading(22, weight: FontWeight.w800, height: 1);
  static TextStyle screenTitle({required bool wide}) => heading(wide ? 24 : 20, weight: const FontWeight(750));
  static TextStyle question({required bool wide}) =>
      heading(wide ? 21 : 18, weight: const FontWeight(650), height: 1.3);
  static TextStyle bigScore({required bool wide}) => heading(
    wide ? 56 : 46,
    weight: FontWeight.w800,
    height: 1,
    letterSpacing: -0.02 * (wide ? 56 : 46),
  ).copyWith(fontFeatures: tabular);
  static TextStyle bodyText() => ui(14.5, height: 1.5);
  static TextStyle small() => ui(13.5, height: 1.45);
  static TextStyle caption() => ui(11.5, height: 1.35);
}
