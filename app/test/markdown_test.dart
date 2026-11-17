import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lea_app/theme/lea_colors.dart';
import 'package:lea_app/widgets/markdown_text.dart';

String plain(List<InlineSpan> spans) => spans.map((s) => s.toPlainText()).join();

void main() {
  group('blocks', () {
    test('paragraphs split on blank lines and keep single line breaks', () {
      final blocks = parseMarkdown('First line\nsecond line\n\nNext paragraph');
      expect(blocks, hasLength(2));
      expect((blocks[0] as MdParagraph).text, 'First line\nsecond line');
      expect((blocks[1] as MdParagraph).text, 'Next paragraph');
    });

    test('numbered and bullet lists, with nesting and continuation lines', () {
      final blocks = parseMarkdown('Steps:\n1. Find faces\n2. Turn each\n   into numbers\n- a\n  - b');
      expect(blocks.first, isA<MdParagraph>());
      final items = blocks.whereType<MdListItem>().toList();
      expect(items.map((i) => i.marker), ['1.', '2.', '•', '•']);
      expect(items[1].text, 'Turn each into numbers');
      expect(items[3].level, 1);
    });

    test('fenced code keeps its lines, even when the fence is still open', () {
      final closed = parseMarkdown('```python\nx = 1\n  y = 2\n```\nafter');
      expect((closed[0] as MdCode).code, 'x = 1\n  y = 2');
      expect((closed[1] as MdParagraph).text, 'after');
      final open = parseMarkdown('```\nprint("hi")');
      expect((open.single as MdCode).code, 'print("hi")');
    });

    test('headings, quotes and rules', () {
      final blocks = parseMarkdown('## Key idea\n> A quote\n---\nText');
      expect((blocks[0] as MdHeading).text, 'Key idea');
      expect((blocks[1] as MdQuote).text, 'A quote');
      expect((blocks[2] as MdParagraph).text, 'Text');
    });
  });

  group('inline', () {
    const base = TextStyle(fontSize: 14.5);
    final c = LeaColors.light;

    test('bold, italic, code and links', () {
      final spans = parseInline(
        'Learns from **labelled examples**, *spam* or _not spam_, `fit()` and [docs](https://x.org).',
        base,
        c,
      );
      expect(plain(spans), 'Learns from labelled examples, spam or not spam, fit() and docs.');
      final bold = spans[1] as TextSpan;
      expect(bold.style!.fontWeight, FontWeight.w600);
      final italic = spans[3] as TextSpan;
      expect(italic.style!.fontStyle, FontStyle.italic);
    });

    test('underscores inside words are not italics', () {
      expect(plain(parseInline('snake_case_name', base, c)), 'snake_case_name');
      expect(parseInline('snake_case_name', base, c), hasLength(1));
    });

    test('an unfinished **bold while streaming shows as typed', () {
      expect(plain(parseInline('This is **impor', base, c)), 'This is **impor');
    });
  });
}
