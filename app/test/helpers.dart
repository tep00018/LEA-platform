import 'dart:async';
import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:lea_app/app.dart';
import 'package:lea_app/auth/token_store.dart';
import 'package:lea_app/providers.dart';

import 'teach_fake.dart';

export 'teach_fake.dart';

const desktop = Size(1224, 800);
const phone = Size(390, 844);

const validToken = 'valid-token';
const alex = {
  'username': 'alex.m',
  'full_name': 'Alex M.',
  'enrolled_courses': ['DEMO101'],
};

/// DEMO101's real outline shape: titles arrive as "Week N: Topic".
Map<String, dynamic> demoOutline({String code = 'DEMO101', String name = 'DEMO101: Introduction to AI/ML'}) => {
  'code': code,
  'name': name,
  'weeks': [
    {
      'number': 1,
      'title': 'Week 1: Introduction to AI',
      'concept_count': 11,
      'learning_objectives': [
        {'id': 'LO1', 'title': 'AI Basics', 'concept_count': 4},
        {'id': 'LO2', 'title': 'AI Types Overview', 'concept_count': 3},
        {'id': 'LO3', 'title': 'AI vs ML Distinction', 'concept_count': 4},
      ],
    },
    {'number': 2, 'title': 'Week 2: Machine Learning Basics', 'concept_count': 9, 'learning_objectives': []},
    {'number': 3, 'title': 'Week 3: Neural Networks', 'concept_count': 12, 'learning_objectives': []},
  ],
};

/// A fake of the LEA API with enough state for the login screen and the shell.
class FakeApi {
  FakeApi({this.currentWeek = 1, List<Map<String, String>>? courses, List<Map<String, String>>? enrolledCourses})
    : courses =
          courses ??
          [
            const {'code': 'DEMO101', 'name': 'DEMO101: Introduction to AI/ML'},
          ],
      enrolledCourses = enrolledCourses == null ? null : List.of(enrolledCourses);

  int currentWeek;

  /// Courses open for enrollment (`GET /courses`; also what a new account can choose from).
  final List<Map<String, String>> courses;

  /// The logged-in student's own courses (`GET/POST/DELETE /me/courses`). Null (the
  /// default): the same as [courses], for tests that don't distinguish the two.
  List<Map<String, String>>? enrolledCourses;

  /// The logged-in account's role (`/me`, login).
  String role = 'student';

  /// The Teacher area's endpoints, when a test needs them.
  FakeTeach? teach;

  /// Alex's profile with [role].
  Map<String, dynamic> get me => {...alex, 'role': role};

  /// A preview (sandbox) token the fake also accepts, for student endpoints (until
  /// [previewExpired]).
  String? get previewToken => previewExpired ? null : teach?.previewToken;

  bool previewExpired = false;

  bool _authorized(http.Request request) {
    final auth = request.headers['Authorization'];
    return auth == 'Bearer $validToken' || (previewToken != null && auth == 'Bearer $previewToken');
  }

  /// Mastered objectives per week, and each week's objective count.
  final mastered = <int, int>{1: 2, 2: 0, 3: 0};
  final totals = <int, int>{1: 11, 2: 9, 3: 12};

  /// Paths that answer with this error until cleared (`{'detail','code'}`, status).
  final failures = <String, (int, Map<String, String>, Map<String, String>)>{};

  /// Paths whose answer waits until the completer completes, to see loading states.
  final holds = <String, Completer<void>>{};

  final requests = <http.Request>[];
  final registered = <Map<String, dynamic>>[];

  http.Response _json(Object body, [int status = 200, Map<String, String> headers = const {}]) =>
      http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json', ...headers});

  /// Chat history for DEMO101, as `GET /chat/{code}/messages` returns it.
  final chatHistory = <Map<String, dynamic>>[];

  /// Bodies sent to the chat stream endpoint.
  final chatSent = <Map<String, dynamic>>[];

  /// The streamed chat reply when [chatStream] isn't set.
  String chatAnswer = 'Supervised learning uses **labelled** data.';

  /// When set, the chat stream's raw SSE text comes from here, chunk by chunk, so a test
  /// can look at the screen between tokens.
  StreamController<String>? chatStream;

  /// DEMO101 Week 1's objectives, grouped by learning objective (4 + 3 + 4).
  static const week1Objectives = {
    'AI Basics': ['Definition Of AI', 'Types Of AI', 'AI Applications', 'AI Limitations'],
    'AI Types Overview': ['Understanding AI Categories', 'Identifying AI Technologies', 'Analyzing AI Applications'],
    'AI vs ML Distinction': ['Defining AI', 'Defining ML', 'Differentiating AI And ML', 'AI And ML Interrelation'],
  };

  static List<String> get week1Skills => [for (final g in week1Objectives.values) ...g];

  /// The tutor session, or null for none. A small simulation of the real tutor: the first
  /// reply is a warm-up (not graded); later replies containing "right" are correct and
  /// move on an objective; after the last objective the session completes.
  Map<String, dynamic>? tutor;
  int _tutorGraded = 0;
  int _tutorCorrect = 0;

  /// Week the student moves on to when a session completes, if any.
  int? tutorAdvancesTo;

  /// When set, the tutor stream's raw SSE text comes from here (the test sends the done
  /// event itself, e.g. built with [tutorDone]).
  StreamController<String>? tutorStream;

  /// The tutor's answer when [tutorStream] isn't set.
  String tutorAnswer = 'Good thinking. Where have you seen AI used?';

  /// Overrides the "contains right" rule for the next replies (non-streamed path).
  bool? tutorCorrect;

  /// Debug/monitoring fields on the tutor view (temporary -- see TutorHeader's
  /// _DebugMetricsPill); null hides that part of the fake, same as an older server would.
  double? tutorObjectiveMastery = 0.36;
  double? tutorCognitiveLoad = 4.35;
  double? tutorZpdScore = 0.5;

  Map<String, dynamic> _tutorView() {
    final index = tutor!['index'] as int;
    return {
      'session_id': 's1',
      'course': tutor!['course'],
      'week': tutor!['week'],
      'completed': tutor!['completed'],
      'progress_percent': 100 * index / week1Skills.length,
      'objective_index': index,
      'objectives_total': week1Skills.length,
      'current_objective': index < week1Skills.length
          ? {'go_id': 'GO${index + 1}', 'skill_name': week1Skills[index]}
          : null,
      'scaffolding_level': 'medium',
      'scaffolding_strategy': 'procedural',
      'messages': tutor!['messages'],
      'advanced_to_week': tutor!['advanced'],
      'current_objective_mastery': tutorObjectiveMastery,
      'cognitive_load': tutorCognitiveLoad,
      'zpd_score': tutorZpdScore,
    };
  }

  void startTutor({
    int week = 1,
    int index = 0,
    String opening = 'Before we start: what do you already know about AI?',
  }) {
    tutor = {
      'course': 'DEMO101',
      'week': week,
      'index': index,
      'completed': false,
      'advanced': null,
      'messages': [
        {'role': 'tutor', 'content': opening, 'timestamp': '2026-09-24T14:10:00'},
      ],
    };
  }

  /// Applies [text] as a student reply and returns the `done` body. Pass `graded: false` to
  /// simulate a non-warm-up reply the tutor still couldn't check (e.g. no recorded question
  /// about the current objective) -- distinct from the warm-up's own, always-ungraded reply.
  Map<String, dynamic> tutorDone(String text, {String? answer, bool? correct, bool? graded}) {
    final messages = tutor!['messages'] as List;
    final warmUp = !messages.any((m) => (m as Map)['role'] == 'student');
    final counts = graded ?? !warmUp;
    correct ??= text.toLowerCase().contains('right');
    messages.add({'role': 'student', 'content': text, 'timestamp': '2026-09-24T14:14:00'});
    if (counts) {
      _tutorGraded++;
      if (correct) {
        _tutorCorrect++;
        final week = tutor!['week'] as int;
        mastered[week] = mastered[week]! + 1;
        tutor!['index'] = (tutor!['index'] as int) + 1;
        if (tutor!['index'] == week1Skills.length) {
          tutor!['completed'] = true;
          tutor!['advanced'] = tutorAdvancesTo;
          if (tutorAdvancesTo != null) currentWeek = tutorAdvancesTo!;
        }
      }
    }
    messages.add({'role': 'tutor', 'content': answer ?? tutorAnswer, 'timestamp': '2026-09-24T14:14:05'});
    return {
      'message': answer ?? tutorAnswer,
      'graded': counts,
      'correct': counts ? correct : null,
      'achievements': <String>[],
      'session': _tutorView(),
    };
  }

  /// Mastery and threshold for Week 1 objectives by number (1-based), when a test wants
  /// specific values.
  final objectiveValues = <int, (double?, double)>{};

  /// Week 1's mastery grouped by learning objective; the first `mastered[1]` are mastered.
  List<Map<String, dynamic>> week1Mastery() {
    var n = 0;
    return [
      for (final (li, MapEntry(key: lo, value: skills)) in week1Objectives.entries.indexed)
        {
          'lo_id': 'LO${li + 1}',
          'title': lo,
          'objectives': [
            for (final skill in skills)
              {
                'go_id': 'GO${++n}',
                'skill_name': skill,
                'mastery': objectiveValues[n]?.$1 ?? (n <= mastered[1]! ? 0.8 : null),
                'threshold': objectiveValues[n]?.$2 ?? 0.65,
                'mastered': n <= mastered[1]!,
              },
          ],
        },
    ];
  }

  /// The quiz's questions, with the right answers the fake grades against (never sent).
  List<Map<String, dynamic>> quizPlan = [
    {
      'type': 'multiple_choice',
      'text':
          "A hospital's AI system was trained on scans from one scanner model. Why might it perform worse "
          'on scans from a different hospital?',
      'options': [
        'A) The AI needs more computing power at the new hospital',
        'B) The new scans differ from the data the AI learned from',
        'C) AI systems stop learning after one year',
        'D) Doctors at the new hospital use it incorrectly',
      ],
      'skill_name': 'AI Limitations',
      'go_id': 'GO4',
      'answer': 'B',
    },
    {
      'type': 'true_false',
      'text': 'Narrow AI is built for one specific task.',
      'options': <String>[],
      'skill_name': 'Understanding AI Categories',
      'go_id': 'GO5',
      'answer': 'True',
    },
    {
      'type': 'fill_in_blank',
      'text': 'A spam filter learns from ______ examples.',
      'options': <String>[],
      'skill_name': 'Defining ML',
      'go_id': 'GO9',
      'answer': 'labelled',
    },
    {
      'type': 'open_ended',
      'text': 'Explain how AI and machine learning are related.\n\n```python\nmodel.fit(examples, labels)\n```',
      'options': <String>[],
      'has_code': true,
      'skill_name': 'AI And ML Interrelation',
      'go_id': 'GO11',
      'answer': null, // open answers here "couldn't be graded"
    },
  ];

  /// The quiz, or null for none.
  Map<String, dynamic>? quiz;

  /// Week the student moves on to when a quiz ends, if any.
  int? quizAdvancesTo;

  Map<String, dynamic> quizView() {
    final q = quiz!;
    final index = q['index'] as int;
    final results = (q['results'] as List).cast<Map<String, dynamic>>();
    final plan = quizPlan[index.clamp(0, quizPlan.length - 1)];
    return {
      'quiz_id': q['id'],
      'course': q['course'],
      'week': q['week'],
      'status': q['status'],
      'position': index + 1,
      'total': quizPlan.length,
      'correct_count': results.where((r) => r['correct'] == true).length,
      'graded_count': results.where((r) => r['correct'] != null).length,
      // Like the real API: the question only while it's being asked.
      'question': q['status'] == 'question'
          ? {
              'number': index + 1,
              'type': plan['type'],
              'text': plan['text'],
              'options': plan['options'],
              'has_code': plan['has_code'] ?? false,
              'skill_name': plan['skill_name'],
            }
          : null,
      'feedback': q['status'] == 'feedback' ? results.last : null,
      'results': results,
      'advanced_to_week': q['advanced'],
    };
  }

  void startQuiz({int week = 1}) {
    quiz = {
      'id': 'q${DateTime.now().microsecondsSinceEpoch}',
      'course': 'DEMO101',
      'week': week,
      'index': 0,
      'status': 'question',
      'results': <Map<String, dynamic>>[],
      'advanced': null,
    };
  }

  http.Response _quizAnswer(String answer) {
    final q = quiz!;
    if (q['status'] != 'question') {
      return _json({'detail': 'This question has already been answered.', 'code': 'WrongState'}, 409);
    }
    final plan = quizPlan[q['index'] as int];
    final expected = plan['answer'] as String?;
    final bool? correct = expected == null
        ? null
        : plan['type'] == 'fill_in_blank'
        ? answer.toLowerCase().contains(expected)
        : answer.trim().toLowerCase() == expected.toLowerCase();
    if (correct == true) mastered[q['week'] as int] = mastered[q['week'] as int]! + 1;
    (q['results'] as List).add({
      'graded': correct != null,
      'correct': correct,
      'score': correct == null ? null : (correct ? 1.0 : 0.0),
      'explanation': correct == null
          ? 'The grader was unavailable for this answer.'
          : (plan['explanation'] as String?) ??
                'New scans can differ from the training data, so the model sees something unfamiliar.',
      'your_answer': answer,
      'correct_answer': correct != null && (plan['type'] == 'multiple_choice' || plan['type'] == 'true_false')
          ? expected
          : null,
      'achievements': <String>[],
      'go_id': plan['go_id'],
    });
    q['status'] = 'feedback';
    return _json(quizView());
  }

  void _finishQuiz() {
    quiz!['status'] = 'completed';
    quiz!['advanced'] = quizAdvancesTo;
    if (quizAdvancesTo != null) currentWeek = quizAdvancesTo!;
  }

  static String sse(String event, Object data) => 'event: $event\ndata: ${jsonEncode(data)}\n\n';

  /// While true every request fails to connect, like a stopped server.
  bool down = false;

  late final client = MockClient.streaming((base, bodyStream) async {
    if (base is! http.Request) {
      // Multipart uploads go to the Teacher area.
      final bytes = await bodyStream.toBytes();
      final r = teach == null
          ? _json({'detail': 'Not found', 'code': 'HTTPError'}, 404)
          : await teach!.handleMultipart(base, bytes);
      return http.StreamedResponse(Stream.value(r.bodyBytes), r.statusCode, headers: r.headers);
    }
    final request = base;
    if (down) {
      requests.add(request);
      throw http.ClientException('Connection refused', request.url);
    }
    final path = request.url.path;
    if (request.method == 'POST' && RegExp(r'^/chat/[^/]+/messages/stream$').hasMatch(path)) {
      requests.add(request);
      await holds[path]?.future;
      final failure = failures[path];
      if (failure != null || !_authorized(request)) {
        final r = failure != null
            ? _json(failure.$2, failure.$1, failure.$3)
            : _json({'detail': 'Please log in again.', 'code': 'NotAuthenticated'}, 401);
        return http.StreamedResponse(Stream.value(r.bodyBytes), r.statusCode, headers: r.headers);
      }
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      chatSent.add(body);
      final Stream<String> chunks;
      if (chatStream != null) {
        chunks = chatStream!.stream;
      } else {
        final words = chatAnswer.split(' ');
        chunks = Stream.fromIterable([
          for (final (i, w) in words.indexed) sse('token', {'text': i == 0 ? w : ' $w'}),
          sse('done', {'ok': true, 'message': chatAnswer}),
        ]);
        final now = DateTime.now().millisecondsSinceEpoch / 1000;
        chatHistory
          ..add({'role': 'user', 'message': body['text'], 'timestamp': now})
          ..add({'role': 'assistant', 'message': chatAnswer, 'timestamp': now});
      }
      return http.StreamedResponse(chunks.map(utf8.encode), 200, headers: {'content-type': 'text/event-stream'});
    }
    if (request.method == 'POST' && path == '/tutor/replies/stream') {
      requests.add(request);
      final failure = failures[path];
      if (failure != null || tutor == null) {
        final r = failure != null
            ? _json(failure.$2, failure.$1, failure.$3)
            : _json({
                'detail': "There's no tutoring session in progress. Start one first.",
                'code': 'NoActiveSession',
              }, 404);
        return http.StreamedResponse(Stream.value(r.bodyBytes), r.statusCode, headers: r.headers);
      }
      final text = (jsonDecode(request.body) as Map<String, dynamic>)['text'] as String;
      final Stream<String> chunks;
      if (tutorStream != null) {
        chunks = tutorStream!.stream;
      } else {
        final done = tutorDone(text, correct: tutorCorrect);
        chunks = Stream.fromIterable([
          sse('token', {'text': tutorAnswer}),
          sse('done', done),
        ]);
      }
      return http.StreamedResponse(chunks.map(utf8.encode), 200, headers: {'content-type': 'text/event-stream'});
    }
    final r = await _handle(request);
    return http.StreamedResponse(Stream.value(r.bodyBytes), r.statusCode, headers: r.headers);
  });

  Future<http.Response> _handle(http.Request request) async {
    requests.add(request);
    final path = request.url.path;
    await holds[path]?.future;
    // The server can go away while a request waits.
    if (down) throw http.ClientException('Connection reset', request.url);
    final failure = failures[path];
    if (failure != null) return _json(failure.$2, failure.$1, failure.$3);

    // No login needed.
    if (path == '/health') return _json({'status': 'ok', 'redis': true});
    if (path == '/courses' && request.method == 'GET') return _json(courses);
    if (path == '/auth/register' && request.method == 'POST') {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      if (body['username'] == 'alex.m') {
        return _json({'detail': 'That username is taken. Choose another.', 'code': 'InvalidInput'}, 400);
      }
      registered.add(body);
      return _json({'message': 'Account created. You can log in now.'}, 201);
    }
    if (path == '/auth/login' && request.method == 'POST') {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      if (body['username'] == 'alex.m' && body['password'] == 'correct horse') {
        return _json({'token': validToken, 'token_type': 'bearer', 'expires_in': 43200, 'user': me});
      }
      return _json({'detail': 'Wrong username or password.', 'code': 'NotAuthenticated'}, 401);
    }

    if (path.startsWith('/teach') || path.startsWith('/admin')) {
      if (request.headers['Authorization'] != 'Bearer $validToken') {
        return _json({'detail': 'Please log in again.', 'code': 'NotAuthenticated'}, 401);
      }
      if (role == 'student' || teach == null || (path.startsWith('/admin') && role != 'admin')) {
        return _json({'detail': 'This area is for teachers.', 'code': 'NotPermitted'}, 403);
      }
      return teach!.handle(request);
    }
    if (!_authorized(request)) {
      return _json({'detail': 'Please log in again.', 'code': 'NotAuthenticated'}, 401);
    }
    if (path == '/me') {
      final preview = previewToken != null && request.headers['Authorization'] == 'Bearer $previewToken';
      return _json(
        preview ? {...alex, 'username': 'alex.m.preview', 'full_name': 'alex.m (preview)', 'role': 'student'} : me,
      );
    }
    if (path == '/me/courses' && request.method == 'GET') return _json(enrolledCourses ?? courses);
    if (path == '/me/courses' && request.method == 'POST') {
      final code = (jsonDecode(request.body) as Map<String, dynamic>)['code'] as String;
      final match = courses.firstWhere((c) => c['code'] == code,
          orElse: () => <String, String>{});
      if (match.isEmpty) return _json({'detail': 'Unknown course: $code.', 'code': 'InvalidInput'}, 400);
      final mine = List.of(enrolledCourses ?? courses);
      if (!mine.any((c) => c['code'] == code)) mine.add(match);
      enrolledCourses = mine;
      return _json(mine, 201);
    }
    final removeMatch = RegExp(r'^/me/courses/([^/]+)$').firstMatch(path);
    if (removeMatch != null && request.method == 'DELETE') {
      final code = removeMatch.group(1);
      final mine = List.of(enrolledCourses ?? courses)..removeWhere((c) => c['code'] == code);
      enrolledCourses = mine;
      return _json(mine);
    }
    if (path == '/auth/logout') return http.Response('', 204);
    if (path == '/quiz') {
      switch (request.method) {
        case 'GET':
          return quiz == null
              ? _json({'detail': "There's no quiz in progress. Start a new quiz.", 'code': 'NoActiveSession'}, 404)
              : _json(quizView());
        case 'POST':
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          if (quiz == null || quiz!['status'] == 'completed' || quiz!['week'] != body['week']) {
            startQuiz(week: body['week'] as int);
          }
          return _json(quizView());
        case 'DELETE':
          quiz = null;
          return http.Response('', 204);
      }
    }
    if (path.startsWith('/quiz/') && request.method == 'POST') {
      if (quiz == null) {
        return _json({'detail': "There's no quiz in progress. Start a new quiz.", 'code': 'NoActiveSession'}, 404);
      }
      switch (path) {
        case '/quiz/answer':
          return _quizAnswer((jsonDecode(request.body) as Map<String, dynamic>)['answer'] as String);
        case '/quiz/next':
          if (quiz!['status'] != 'feedback') {
            return _json({'detail': 'Answer the current question first.', 'code': 'WrongState'}, 409);
          }
          if ((quiz!['index'] as int) + 1 >= quizPlan.length) {
            _finishQuiz();
          } else {
            quiz!['index'] = (quiz!['index'] as int) + 1;
            quiz!['status'] = 'question';
          }
          return _json(quizView());
        case '/quiz/end':
          if (quiz!['status'] != 'completed') _finishQuiz();
          return _json(quizView());
      }
    }
    if (path == '/tutor') {
      if (request.method == 'GET') {
        if (tutor == null) {
          return _json({'detail': "There's no tutoring session in progress.", 'code': 'NoActiveSession'}, 404);
        }
        return _json(_tutorView());
      }
      if (request.method == 'POST') {
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        if (body['review_quiz'] == true) {
          startTutor(week: body['week'] as int, opening: "Let's go over your Week ${body['week']} quiz.");
        } else if (tutor == null || tutor!['week'] != body['week'] || tutor!['completed'] == true) {
          startTutor(week: body['week'] as int);
        }
        return _json(_tutorView());
      }
    }
    if (path == '/tutor/end' && request.method == 'POST') {
      if (tutor == null) return _json({'detail': 'No session.', 'code': 'NoActiveSession'}, 404);
      final summary = {
        'total_gos': week1Skills.length,
        'gos_completed': tutor!['index'],
        'gos_mastered': _tutorCorrect,
        'accuracy': _tutorGraded == 0 ? 0.0 : _tutorCorrect / _tutorGraded,
        'interaction_count': (tutor!['messages'] as List).where((m) => (m as Map)['role'] == 'student').length,
        'advanced_to_week': tutor!['advanced'],
      };
      tutor = null;
      return _json(summary);
    }
    if (RegExp(r'^/chat/[^/]+/messages$').hasMatch(path)) {
      if (request.method == 'GET') return _json(chatHistory);
      if (request.method == 'DELETE') {
        chatHistory.clear();
        return http.Response('', 204);
      }
    }

    final course = RegExp(r'^/courses/([^/]+)/(outline|progress|mastery)$').firstMatch(path);
    if (course != null) {
      final code = course.group(1)!;
      final match = courses.where((c) => c['code'] == code);
      if (match.isEmpty) return _json({'detail': "You're not enrolled in $code.", 'code': 'NotEnrolled'}, 403);
      switch (course.group(2)) {
        case 'outline':
          return _json(demoOutline(code: code, name: match.first['name']!));
        case 'progress':
          return _json({
            'course': code,
            'current_week': currentWeek,
            'week_completion': mastered[currentWeek]! / totals[currentWeek]!,
            'completed_gos': [],
            'total_gos': totals[currentWeek],
            'ready_for_next_week': false,
          });
        case 'mastery':
          final week = int.parse(request.url.queryParameters['week']!);
          return _json({
            'course': code,
            'week': week,
            'completion': mastered[week]! / totals[week]!,
            'mastered_count': mastered[week],
            'total': totals[week],
            'learning_objectives': week == 1 ? week1Mastery() : [],
          });
      }
    }
    return _json({'detail': 'Not found', 'code': 'HTTPError'}, 404);
  }

  /// How many requests went to [path].
  int calls(String path) => requests.where((r) => r.url.path == path).length;
}

/// Pumps the whole app at [size] in [brightness], against [api], with [token] saved.
Future<({FakeApi api, MemoryTokenStore store})> pumpLea(
  WidgetTester tester, {
  Size size = desktop,
  Brightness brightness = Brightness.light,
  String? token = validToken,
  FakeApi? api,
  List<Override> overrides = const [],
}) async {
  final fake = api ?? FakeApi();
  final store = MemoryTokenStore(token);
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  tester.platformDispatcher.platformBrightnessTestValue = brightness;
  addTearDown(tester.view.reset);
  addTearDown(tester.platformDispatcher.clearPlatformBrightnessTestValue);

  await tester.pumpWidget(
    ProviderScope(
      retry: noRetry,
      overrides: [
        httpClientProvider.overrideWithValue(fake.client),
        tokenStoreProvider.overrideWithValue(store),
        apiBaseUrlProvider.overrideWithValue('http://lea.test'),
        ...overrides,
      ],
      child: const LeaApp(),
    ),
  );
  await tester.pumpAndSettle();
  return (api: fake, store: store);
}

/// Loads the app's real fonts (flutter test otherwise draws every glyph as a 1 em box),
/// for tests where text width matters.
Future<void> loadAppFonts() async {
  for (final (family, file) in [
    ('Lexend', 'assets/fonts/Lexend-Variable.ttf'),
    ('Bricolage Grotesque', 'assets/fonts/BricolageGrotesque-Variable.ttf'),
    ('JetBrains Mono', 'assets/fonts/JetBrainsMono-Variable.ttf'),
    ('MaterialIcons', 'fonts/MaterialIcons-Regular.otf'),
  ]) {
    await (FontLoader(family)..addFont(rootBundle.load(file))).load();
  }
}
