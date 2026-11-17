import 'package:flutter/material.dart';

import '../../api/models.dart';
import '../../theme/lea_colors.dart';
import '../../theme/lea_type.dart';
import '../../widgets/markdown_text.dart';
import '../../widgets/meter.dart';
import '../../widgets/pressable.dart';

/// Shortest open answer the app accepts (DESIGN.md: "character count (min 10)").
const openAnswerMin = 10;

/// The header band over a quiz: "Question 4 of 11 · AI Basics", "Correct so far 2 / 3",
/// and a meter for how far through the quiz you are.
class QuizBar extends StatelessWidget {
  const QuizBar({super.key, required this.quiz, required this.loTitle, required this.wide});

  final QuizView quiz;
  final String? loTitle;
  final bool wide;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final base = LeaType.ui(13, height: 1.5).copyWith(color: c.muted, fontFeatures: LeaType.tabular);
    final bold = TextStyle(
      color: c.ink,
      fontWeight: FontWeight.w600,
      fontVariations: const [FontVariation.weight(600)],
    );
    return Container(
      padding: EdgeInsets.symmetric(horizontal: wide ? 22 : 16, vertical: 14),
      decoration: BoxDecoration(
        color: c.bg,
        border: Border(bottom: BorderSide(color: c.line)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Wrap(
            alignment: WrapAlignment.spaceBetween,
            runSpacing: 6,
            spacing: 16,
            children: [
              Text.rich(
                TextSpan(
                  style: base,
                  children: [
                    const TextSpan(text: 'Question '),
                    TextSpan(text: '${quiz.position}', style: bold),
                    TextSpan(text: ' of ${quiz.total}'),
                    if (loTitle != null) TextSpan(text: ' · $loTitle'),
                  ],
                ),
              ),
              Text.rich(
                TextSpan(
                  style: base,
                  children: [
                    const TextSpan(text: 'Correct so far '),
                    TextSpan(text: '${quiz.correctCount}', style: bold),
                    TextSpan(text: ' / ${quiz.gradedCount}'),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Meter(value: quiz.total == 0 ? 0 : quiz.position / quiz.total, semanticLabel: 'Quiz progress'),
        ],
      ),
    );
  }
}

/// How an option card looks.
enum OptionLook { idle, selected, wrong, right, yours }

/// An option as a card with a letter chip (A–D). Selected: `primary` border plus a 1 px
/// inset and a filled chip. After answering: the wrong choice on `danger-soft` with
/// "Your answer", the right one on `success-soft` with "Correct answer".
class OptionCard extends StatelessWidget {
  const OptionCard({
    super.key,
    required this.letter,
    required this.text,
    required this.look,
    this.label,
    this.onTap,
    this.large = false,
  });

  /// Null for true/false cards, which have no chip.
  final String? letter;
  final String text;
  final OptionLook look;

  /// "Your answer" / "Correct answer".
  final String? label;
  final VoidCallback? onTap;

  /// True/false: two large cards.
  final bool large;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final (border, width, fill, chipFill, chipText, labelColor) = switch (look) {
      OptionLook.idle => (c.line, 1.5, c.surface, c.surface2, c.ink, c.muted),
      OptionLook.selected => (c.primary, 2.5, c.surface, c.primary, c.onPrimary, c.primary),
      OptionLook.wrong => (c.danger, 1.5, c.dangerSoft, c.danger, c.surface, c.danger),
      OptionLook.right => (c.success, 1.5, c.successSoft, c.success, c.surface, c.success),
      OptionLook.yours => (c.muted, 1.5, c.surface, c.surface2, c.ink, c.muted),
    };
    final semantics = [
      if (letter != null) 'Option $letter',
      text,
      ?label,
      if (look == OptionLook.selected) 'selected',
    ].join(', ');

    final card = Container(
      constraints: BoxConstraints(minHeight: large ? 64 : 0),
      // Keep the content still when the border thickens.
      padding: EdgeInsets.symmetric(horizontal: 14 - (width - 1.5), vertical: 12 - (width - 1.5)),
      decoration: BoxDecoration(
        color: fill,
        border: Border.all(color: border, width: width),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        children: [
          if (letter != null) ...[
            Container(
              width: 28,
              height: 28,
              alignment: Alignment.center,
              decoration: BoxDecoration(color: chipFill, borderRadius: BorderRadius.circular(8)),
              child: Text(
                letter!,
                style: LeaType.ui(13, weight: FontWeight.w600).copyWith(color: chipText),
              ),
            ),
            const SizedBox(width: 12),
          ],
          Expanded(
            child: Text(
              text,
              style: large
                  ? LeaType.ui(16, weight: FontWeight.w500, height: 1.4).copyWith(color: c.ink)
                  : LeaType.ui(14.5, height: 1.5).copyWith(color: c.ink),
            ),
          ),
          if (label != null) ...[
            const SizedBox(width: 10),
            Text(
              label!,
              style: LeaType.ui(12, weight: FontWeight.w600).copyWith(color: labelColor),
            ),
          ],
        ],
      ),
    );

    if (onTap == null) return Semantics(label: semantics, excludeSemantics: true, child: card);
    return Pressable(
      onTap: onTap,
      borderRadius: 12,
      selected: look == OptionLook.selected,
      semanticLabel: semantics,
      excludeChildSemantics: true,
      child: card,
    );
  }
}

/// The question's kicker ("MULTIPLE CHOICE   AI LIMITATIONS") and text (Bricolage; code
/// in a monospace block).
class QuestionText extends StatelessWidget {
  const QuestionText({super.key, required this.question, required this.wide});

  final QuizQuestion question;
  final bool wide;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final kicker = LeaType.label(11.5).copyWith(color: c.muted, letterSpacing: 0.07 * 11.5);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Wrap(
          spacing: 12,
          runSpacing: 4,
          children: [
            Text(question.typeLabel.toUpperCase(), style: kicker),
            if (question.skillName.isNotEmpty) Text(question.skillName.toUpperCase(), style: kicker),
          ],
        ),
        const SizedBox(height: 16),
        Semantics(
          header: true,
          child: MarkdownText(
            question.text,
            style: LeaType.question(wide: wide).copyWith(color: c.ink),
          ),
        ),
      ],
    );
  }
}

/// "Correct." / "Not quite." / "Couldn't grade this one", then the explanation.
class FeedbackBox extends StatelessWidget {
  const FeedbackBox({super.key, required this.feedback});

  final QuizFeedback feedback;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    final (title, color, fill) = switch (feedback.correct) {
      true => ('Correct.', c.success, c.successSoft),
      false => ('Not quite.', c.danger, c.dangerSoft),
      null => ("Couldn't grade this one", c.muted, c.surface2),
    };
    final body = [
      if (feedback.correct == null) "This answer doesn't count towards your score.",
      if (feedback.explanation.trim().isNotEmpty) feedback.explanation.trim(),
    ].join(' ');
    return Semantics(
      liveRegion: true,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        decoration: BoxDecoration(
          color: fill,
          border: Border.all(color: color, width: 1.5),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              title,
              style: LeaType.heading(
                17,
                weight: FontWeight.w700,
              ).copyWith(color: feedback.correct == null ? c.ink : color),
            ),
            if (body.isNotEmpty) ...[
              const SizedBox(height: 4),
              MarkdownText(body, style: LeaType.ui(14.5, height: 1.55).copyWith(color: c.ink)),
            ],
          ],
        ),
      ),
    );
  }
}

/// The answer area for a question, and how the student's answer looks after feedback.
///
/// Multiple choice and true/false are cards; fill in the blank is one input; open answers
/// are a text area with a character count. [value] is the letter, "True"/"False", or text.
class AnswerArea extends StatelessWidget {
  const AnswerArea({
    super.key,
    required this.question,
    required this.value,
    required this.onChanged,
    required this.controller,
    this.feedback,
    this.onSubmit,
  });

  final QuizQuestion question;
  final String? value;
  final ValueChanged<String> onChanged;

  /// For the free-text types.
  final TextEditingController controller;

  /// Set after answering: the cards show right and wrong, inputs are read-only.
  final QuizFeedback? feedback;

  /// Enter in the fill-in-the-blank input.
  final VoidCallback? onSubmit;

  bool get _answered => feedback != null;

  OptionLook _look(String key) {
    final f = feedback;
    if (f == null) return key == value ? OptionLook.selected : OptionLook.idle;
    final yours = _same(key, f.yourAnswer);
    final right = f.correctAnswer != null && _same(key, f.correctAnswer!);
    if (right) return OptionLook.right;
    if (yours) return f.correct == false ? OptionLook.wrong : (f.correct == true ? OptionLook.right : OptionLook.yours);
    return OptionLook.idle;
  }

  String? _label(String key) {
    final f = feedback;
    if (f == null) return null;
    if (_same(key, f.yourAnswer)) return 'Your answer';
    if (f.correctAnswer != null && _same(key, f.correctAnswer!)) return 'Correct answer';
    return null;
  }

  static bool _same(String key, String answer) {
    final a = answer.trim().toLowerCase();
    final k = key.toLowerCase();
    return a == k || a.startsWith('$k)') || a.startsWith('$k.') || a == 'option $k';
  }

  @override
  Widget build(BuildContext context) {
    switch (question.type) {
      case 'multiple_choice':
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            for (final (i, choice) in question.choices.indexed) ...[
              if (i > 0) const SizedBox(height: 8),
              OptionCard(
                letter: choice.letter,
                text: choice.text,
                look: _look(choice.letter),
                label: _label(choice.letter),
                onTap: _answered ? null : () => onChanged(choice.letter),
              ),
            ],
          ],
        );
      case 'true_false':
        return Row(
          children: [
            for (final (i, option) in const ['True', 'False'].indexed) ...[
              if (i > 0) const SizedBox(width: 10),
              Expanded(
                child: OptionCard(
                  letter: null,
                  text: option,
                  large: true,
                  look: _look(option),
                  label: _label(option),
                  onTap: _answered ? null : () => onChanged(option),
                ),
              ),
            ],
          ],
        );
      default:
        return _FreeText(
          controller: controller,
          open: question.type == 'open_ended',
          readOnly: _answered,
          onChanged: onChanged,
          onSubmit: onSubmit,
        );
    }
  }
}

class _FreeText extends StatelessWidget {
  const _FreeText({
    required this.controller,
    required this.open,
    required this.readOnly,
    required this.onChanged,
    required this.onSubmit,
  });

  final TextEditingController controller;
  final bool open;
  final bool readOnly;
  final ValueChanged<String> onChanged;
  final VoidCallback? onSubmit;

  @override
  Widget build(BuildContext context) {
    final c = context.lea;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ExcludeSemantics(
          child: Text(
            'Your answer',
            style: LeaType.ui(13, weight: FontWeight.w500).copyWith(color: c.ink),
          ),
        ),
        const SizedBox(height: 6),
        Semantics(
          label: 'Your answer',
          child: TextField(
            controller: controller,
            readOnly: readOnly,
            onChanged: onChanged,
            onSubmitted: open ? null : (_) => onSubmit?.call(),
            minLines: open ? 4 : 1,
            maxLines: open ? 10 : 1,
            maxLength: 4000,
            buildCounter: (_, {required currentLength, required isFocused, maxLength}) => null,
            textInputAction: open ? TextInputAction.newline : TextInputAction.done,
            keyboardType: open ? TextInputType.multiline : TextInputType.text,
            style: LeaType.ui(14.5, height: 1.5).copyWith(color: c.ink),
            decoration: const InputDecoration(contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 11)),
          ),
        ),
        if (open && !readOnly) ...[
          const SizedBox(height: 6),
          ListenableBuilder(
            listenable: controller,
            builder: (context, _) {
              final n = controller.text.trim().length;
              return Text(
                n < openAnswerMin ? '$n characters · at least $openAnswerMin' : '$n character${n == 1 ? '' : 's'}',
                style: LeaType.caption().copyWith(color: c.muted, fontFeatures: LeaType.tabular),
              );
            },
          ),
        ],
      ],
    );
  }
}
