import 'package:flutter/material.dart';

import '../theme/lea_colors.dart';
import '../theme/lea_type.dart';

/// Renders the Markdown LEA's replies use: paragraphs, **bold**, *italic*, `code`,
/// fenced code blocks, bullet and numbered lists (nested by indent), headings,
/// block quotes and links (shown as underlined text).
///
/// It is deliberately small and forgiving: a reply that is still streaming may end in
/// the middle of `**bold` or a code fence, and that must still render sensibly.
class MarkdownText extends StatelessWidget {
  const MarkdownText(this.source, {super.key, required this.style, this.trailing});

  final String source;
  final TextStyle style;

  /// Placed at the end of the last line, e.g. the streaming cursor.
  final InlineSpan? trailing;

  @override
  Widget build(BuildContext context) {
    final blocks = parseMarkdown(source);
    if (blocks.isEmpty) {
      return Text.rich(TextSpan(children: [?trailing]), style: style);
    }
    final children = <Widget>[];
    for (final (i, block) in blocks.indexed) {
      final last = i == blocks.length - 1;
      if (i > 0) children.add(SizedBox(height: block is MdListItem && blocks[i - 1] is MdListItem ? 2 : 6));
      children.add(_block(context, block, last ? trailing : null));
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: children);
  }

  Widget _block(BuildContext context, MdBlock block, InlineSpan? trailing) {
    final c = context.lea;
    List<InlineSpan> inline(String text) => [...parseInline(text, style, c), ?trailing];

    switch (block) {
      case MdParagraph(:final text):
        return Text.rich(TextSpan(children: inline(text)), style: style);
      case MdHeading(:final text):
        return Text.rich(
          style: style.copyWith(fontWeight: FontWeight.w600, fontVariations: const [FontVariation.weight(600)]),
          TextSpan(children: inline(text)),
        );
      case MdQuote(:final text):
        return Container(
          padding: const EdgeInsets.only(left: 10),
          decoration: BoxDecoration(
            border: Border(left: BorderSide(color: c.line, width: 3)),
          ),
          child: Text.rich(
            style: style.copyWith(color: c.muted),
            TextSpan(children: inline(text)),
          ),
        );
      case MdCode(:final code):
        return Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
          decoration: BoxDecoration(color: c.surface2, borderRadius: BorderRadius.circular(8)),
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Text.rich(
              style: LeaType.mono(style.fontSize! - 1).copyWith(color: c.ink),
              TextSpan(
                children: [
                  TextSpan(text: code),
                  ?trailing,
                ],
              ),
            ),
          ),
        );
      case MdListItem(:final marker, :final text, :final level):
        return Padding(
          padding: EdgeInsets.only(left: 4.0 + level * 18),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                width: 18,
                child: Text(marker, style: style.copyWith(fontFeatures: LeaType.tabular)),
              ),
              Expanded(
                child: Text.rich(TextSpan(children: inline(text)), style: style),
              ),
            ],
          ),
        );
    }
  }
}

// ---- Blocks ----

sealed class MdBlock {
  const MdBlock();
}

class MdParagraph extends MdBlock {
  const MdParagraph(this.text);
  final String text;
}

class MdHeading extends MdBlock {
  const MdHeading(this.text);
  final String text;
}

class MdQuote extends MdBlock {
  const MdQuote(this.text);
  final String text;
}

class MdCode extends MdBlock {
  const MdCode(this.code);
  final String code;
}

class MdListItem extends MdBlock {
  const MdListItem({required this.marker, required this.text, required this.level});

  /// "•" for bullets, "3." for numbered items.
  final String marker;
  final String text;
  final int level;
}

final _fence = RegExp(r'^\s*(```|~~~)');
final _heading = RegExp(r'^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$');
final _bullet = RegExp(r'^(\s*)[-*+]\s+(.*)$');
final _numbered = RegExp(r'^(\s*)(\d{1,3})[.)]\s+(.*)$');
final _quote = RegExp(r'^\s*>\s?(.*)$');
final _rule = RegExp(r'^\s*([-*_])(\s*\1){2,}\s*$');

/// Splits Markdown into blocks. Lines inside a paragraph keep their line breaks,
/// because chat replies use single newlines as real breaks.
List<MdBlock> parseMarkdown(String source) {
  final lines = source.replaceAll('\r\n', '\n').split('\n');
  final blocks = <MdBlock>[];
  final paragraph = <String>[];

  void flush() {
    if (paragraph.isNotEmpty) {
      blocks.add(MdParagraph(paragraph.join('\n')));
      paragraph.clear();
    }
  }

  for (var i = 0; i < lines.length; i++) {
    final line = lines[i];

    if (_fence.hasMatch(line)) {
      flush();
      final code = <String>[];
      i++;
      while (i < lines.length && !_fence.hasMatch(lines[i])) {
        code.add(lines[i]);
        i++;
      }
      blocks.add(MdCode(code.join('\n')));
      continue;
    }
    if (line.trim().isEmpty) {
      flush();
      continue;
    }
    if (_rule.hasMatch(line)) {
      flush();
      continue;
    }
    final heading = _heading.firstMatch(line);
    if (heading != null) {
      flush();
      blocks.add(MdHeading(heading.group(1)!));
      continue;
    }
    final bullet = _bullet.firstMatch(line);
    final numbered = bullet == null ? _numbered.firstMatch(line) : null;
    if (bullet != null || numbered != null) {
      flush();
      final indent = (bullet ?? numbered)!.group(1)!.replaceAll('\t', '    ').length;
      blocks.add(
        MdListItem(
          marker: bullet != null ? '•' : '${numbered!.group(2)}.',
          text: bullet != null ? bullet.group(2)! : numbered!.group(3)!,
          level: (indent ~/ 2).clamp(0, 3),
        ),
      );
      continue;
    }
    final quote = _quote.firstMatch(line);
    if (quote != null) {
      flush();
      blocks.add(MdQuote(quote.group(1)!));
      continue;
    }
    // An indented line straight after a list item continues it.
    if (paragraph.isEmpty && blocks.isNotEmpty && blocks.last is MdListItem && line.startsWith(RegExp(r'\s{2,}'))) {
      final item = blocks.removeLast() as MdListItem;
      blocks.add(MdListItem(marker: item.marker, text: '${item.text} ${line.trim()}', level: item.level));
      continue;
    }
    paragraph.add(line.trimRight());
  }
  flush();
  return blocks;
}

// ---- Inline ----

final _inline = RegExp(
  r'(`[^`\n]+`)' // code
  r'|(\*\*(?=\S)[\s\S]+?\*\*)' // **bold**
  r'|(__(?=\S)[\s\S]+?__)' // __bold__
  r'|(\*(?=[^\s*])[^*\n]+?\*)' // *italic*
  r'|((?<![A-Za-z0-9_])_(?=[^\s_])[^_\n]+?_(?![A-Za-z0-9_]))' // _italic_
  r'|(\[[^\]\n]+\]\([^)\s]+\))', // [text](url)
);

/// Inline Markdown as text spans on top of [base].
List<InlineSpan> parseInline(String text, TextStyle base, LeaColors c) {
  final spans = <InlineSpan>[];
  var at = 0;
  for (final m in _inline.allMatches(text)) {
    if (m.start > at) spans.add(TextSpan(text: text.substring(at, m.start)));
    final token = m.group(0)!;
    if (m.group(1) != null) {
      spans.add(
        TextSpan(
          text: token.substring(1, token.length - 1),
          style: LeaType.mono((base.fontSize ?? 14.5) - 1).copyWith(backgroundColor: c.surface2),
        ),
      );
    } else if (m.group(2) != null || m.group(3) != null) {
      spans.add(
        TextSpan(
          style: const TextStyle(fontWeight: FontWeight.w600, fontVariations: [FontVariation.weight(600)]),
          children: parseInline(token.substring(2, token.length - 2), base, c),
        ),
      );
    } else if (m.group(4) != null || m.group(5) != null) {
      spans.add(
        TextSpan(
          style: const TextStyle(fontStyle: FontStyle.italic),
          children: parseInline(token.substring(1, token.length - 1), base, c),
        ),
      );
    } else {
      final label = token.substring(1, token.indexOf(']('));
      spans.add(
        TextSpan(
          text: label,
          style: const TextStyle(decoration: TextDecoration.underline),
        ),
      );
    }
    at = m.end;
  }
  if (at < text.length) spans.add(TextSpan(text: text.substring(at)));
  return spans;
}
