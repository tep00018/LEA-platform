import 'dart:convert';

import 'package:http/http.dart' as http;

/// A fake of the Teacher-area API (`/teach/...`), with enough state for its screens.
class FakeTeach {
  FakeTeach({List<Map<String, dynamic>>? courses})
    : courses = courses ?? [course('AIML101', 'Introduction to AI and Machine Learning', live: true)];

  static Map<String, dynamic> course(
    String code,
    String name, {
    bool live = false,
    bool managed = false,
    int weeks = 2,
    String? activeJob,
    List<String> owners = const ['alex.m'],
  }) => {
    'code': code,
    'name': name,
    'owners': owners,
    'managed': managed,
    'uploads': 0,
    'active_job': activeJob,
    'has_kc_model': live,
    'has_content': live,
    'weeks': weeks,
    'learning_objectives': live ? 2 : 0,
    'granular_objectives': live ? 4 : 0,
  };

  final List<Map<String, dynamic>> courses;
  final requests = <http.BaseRequest>[];
  final bodies = <String, List<Object?>>{};

  // ------------------------------------------------------------------ setup state
  final plans = <String, Map<String, dynamic>>{};
  final uploads = <String, List<Map<String, dynamic>>>{};
  final jobs = <String, Map<String, dynamic>>{};
  int _jobs = 0;

  // ------------------------------------------------------------------ linked materials source
  List<String> materialsFolders = ['AIML101', 'PSYC101'];
  final materialsSources = <String, Map<String, dynamic>?>{};

  /// Sync-preview entries per course; the test sets these directly to script a scenario.
  final syncPreviewEntries = <String, List<Map<String, dynamic>>>{};

  // ------------------------------------------------------------------ KC state
  final drafts = <String, Map<String, dynamic>>{};
  int publishedVersion = 1;
  final published = <String, List<Map<String, dynamic>>>{'AIML101': kcRows()};

  // ------------------------------------------------------------------ videos state
  /// Videos per course and objective, in the order students see them.
  final videos = <String, Map<String, List<Map<String, dynamic>>>>{};

  /// Is automatic YouTube search configured, and until when is it paused (an ISO time or null)?
  bool searchEnabled = true;
  String? quotaPausedUntil;

  /// Students shown video help per objective: missing = 0, present with null = 1 to 4 (withheld).
  final helpShown = <String, int?>{};
  int? helpShownTimes;

  // ------------------------------------------------------------------ analytics state
  /// Real students have fewer than 5 so far; the simulated cohort has 31.
  bool chatGrouped = false;
  int explainers = 0;

  static Map<String, dynamic> stats(
    String go,
    String name,
    int week,
    String band, {
    int? students,
    String? level,
    String? driver,
    double? first,
    double? toMaster,
    String? verdict,
  }) => {
    'go_id': go,
    'skill_name': name,
    'week': week,
    'lo_id': 'LO_0${week}_01',
    'threshold': 0.7,
    'band': band,
    'students': students,
    'suppressed': students == null,
    'graded_attempts': students == null ? null : students * 7,
    'first_attempt_accuracy': first,
    'attempts_to_master': toMaster,
    'curve_verdict': verdict,
    'attention': {'score': level == null ? null : 0.5, 'level': level, 'driver': driver, 'factors': <String, double>{}},
  };

  List<Map<String, dynamic>> _objectives(bool simulated) => simulated
      ? [
          stats(
            'GO_01_01_001',
            'Implement gradient descent',
            1,
            'struggling',
            students: 31,
            level: 'high',
            driver: 'a flat learning curve',
            first: 0.38,
            toMaster: 7.2,
            verdict: 'flat',
          ),
          stats(
            'GO_01_01_002',
            'MLP architecture',
            1,
            'mastered',
            students: 33,
            level: 'low',
            first: 0.81,
            toMaster: 2.1,
            verdict: 'declining',
          ),
          stats('GO_02_02_003', 'Framework ecosystem support', 2, 'insufficient'),
        ]
      : [
          stats('GO_01_01_001', 'Implement gradient descent', 1, 'insufficient'),
          stats('GO_01_01_002', 'MLP architecture', 1, 'insufficient'),
        ];

  http.Response _videos(String code, String rest, String method, Object? body) {
    final lists = videos.putIfAbsent(code, () => {});
    final rows = published[code] ?? const <Map<String, dynamic>>[];
    if (method == 'GET' && rest == '/videos') {
      final paused = searchEnabled && quotaPausedUntil != null;
      return _json({
        'course': code,
        'max_per_objective': 5,
        'search': {'enabled': searchEnabled, 'quota_paused_until': quotaPausedUntil, 'cached_searches': 2},
        'curated_objectives': lists.values.where((l) => l.isNotEmpty).length,
        'help_window_days': 30,
        'help_shown_times': helpShownTimes,
        'objectives': [
          for (final r in rows)
            {
              'go_id': r['go_id'],
              'week': r['week'],
              'lo_id': r['lo_id'],
              'skill_name': r['skill_name'],
              'videos': lists[r['go_id']] ?? const <Map<String, dynamic>>[],
              'student_gets': (lists[r['go_id']] ?? const []).isNotEmpty
                  ? 'curated'
                  : (searchEnabled && !paused ? 'search' : 'links'),
              'help_shown_students': helpShown.containsKey(r['go_id']) ? helpShown[r['go_id']] : 0,
            },
        ],
      });
    }
    if (method == 'POST' && rest == '/videos') {
      final b = body as Map<String, dynamic>;
      final go = b['go_id'] as String;
      if (!rows.any((r) => r['go_id'] == go)) {
        return _error("That objective isn't in the live version of this course.", 'NotFound', 404);
      }
      final url = (b['url'] as String? ?? '').trim();
      final id = RegExp(r'(?:youtu\.be/|watch\?v=)([A-Za-z0-9_-]{11})').firstMatch(url)?.group(1);
      if (id == null) {
        return _error(
          "That isn't a YouTube link. Paste the address of a video on youtube.com or youtu.be.",
          'InvalidInput',
          400,
        );
      }
      if (id.startsWith('private')) {
        return _error(
          "YouTube can't show that video: it may be private, removed, age-restricted or not allowed to be "
              'embedded. Check the link, or choose another video.',
          'InvalidInput',
          400,
        );
      }
      final list = lists.putIfAbsent(go, () => []);
      if (list.any((v) => v['id'] == id)) {
        return _error("That video is already in this objective's list.", 'InvalidInput', 400);
      }
      if (list.length >= 5) {
        return _error('An objective can have up to 5 videos. Remove one first.', 'InvalidInput', 400);
      }
      final video = {
        'id': id,
        'url': 'https://www.youtube.com/watch?v=$id',
        'title': 'Title of $id',
        'channel': 'A Channel',
        'note': (b['note'] as String? ?? '').trim(),
        'added_by': 'alex.m',
        'added_at': '2026-09-12T10:00:00+00:00',
      };
      list.add(video);
      return _json(video, 201);
    }
    final m = RegExp(r'^/videos/([^/]+)/([^/]+)(/move)?$').firstMatch(rest);
    if (m != null) {
      final list = lists[m.group(1)!] ?? [];
      final index = list.indexWhere((v) => v['id'] == m.group(2));
      if (index < 0) return _error("That video isn't in this objective's list.", 'NotFound', 404);
      if (method == 'DELETE') {
        list.removeAt(index);
        return http.Response('', 204);
      }
      if (method == 'POST' && m.group(3) != null) {
        final up = (body as Map<String, dynamic>)['direction'] == 'up';
        final target = index + (up ? -1 : 1);
        if (target >= 0 && target < list.length) {
          final tmp = list[index];
          list[index] = list[target];
          list[target] = tmp;
        }
        return _json(list);
      }
    }
    return _error('Not found', 'HTTPError', 404);
  }

  http.Response _analytics(String rest, String method, http.Request request) {
    final simulated = request.url.queryParameters['kind'] == 'simulated';
    final week = int.tryParse(request.url.queryParameters['week'] ?? '');
    switch ((method, rest)) {
      case ('GET', '/analytics'):
        final objectives = [
          for (final o in _objectives(simulated))
            if (week == null || o['week'] == week) o,
        ];
        return _json({
          'course': 'AIML101',
          'kind': simulated ? 'simulated' : 'real',
          'week': week,
          'min_students': 5,
          'students': simulated ? 42 : null,
          'suppressed': !simulated,
          'bands': {
            for (final b in ['struggling', 'developing', 'mastered', 'insufficient'])
              b: objectives.where((o) => o['band'] == b).length,
          },
          'objectives': objectives,
          'usage': simulated
              ? {'active_students': 38, 'sessions': 214, 'chat_questions': 90, 'hours': 61.4, 'suppressed': false}
              : {'suppressed': true},
          'kc_version': publishedVersion,
        });
      case ('GET', '/analytics/curves.csv'):
        return http.Response.bytes(
          utf8.encode('KC (granular objective),Opportunity'),
          200,
          headers: {'content-type': 'text/csv'},
        );
      case ('GET', '/analytics/chat-topics'):
        return _json({
          'result': chatGrouped ? _chatResult() : null,
          'questions': simulated ? 90 : 3,
          'students': simulated ? 30 : null,
          'usd': 0.004,
          'can_run': simulated,
        });
      case ('POST', '/analytics/chat-topics'):
        chatGrouped = true;
        return _json(_chatResult());
    }
    final detail = RegExp(r'^/analytics/objectives/([^/]+)(/explainer)?$').firstMatch(rest);
    if (detail != null && detail.group(2) != null && method == 'POST') {
      explainers++;
      return _json({
        'go_id': detail.group(1),
        'text': 'Gradient descent moves against the slope.',
        'model': 'gpt-4o-mini',
        'note': 'A draft for you to edit. LEA never publishes it.',
      });
    }
    if (detail != null && method == 'GET') {
      final o = _objectives(simulated).where((x) => x['go_id'] == detail.group(1)).firstOrNull;
      if (o == null) return _error('No such objective in the live version.', 'NotFound', 404);
      final shown = o['students'] != null;
      return _json({
        ...o,
        'description': '',
        'curve': [
          for (var k = 1; k <= 7; k++) {'opportunity': k, 'students': 31, 'error_rate': shown ? 0.6 : null},
        ],
        'course_curve': [
          for (var k = 1; k <= 7; k++) {'opportunity': k, 'students': 40, 'error_rate': shown ? 0.55 / k : null},
        ],
        'wrong_answers': shown
            ? {
                'suppressed': false,
                'students': 20,
                'answers': [
                  {'answer': 'subtract the gradient from the loss', 'share': 0.41, 'count': 9},
                ],
              }
            : {'suppressed': true, 'students': null, 'answers': <Object>[]},
        'struggle': shown
            ? {'streak_students': 9, 'video_students': 7, 'sessions_left_stuck': 5, 'suppressed': false}
            : {'suppressed': true},
        'chat_topics': chatGrouped && o['go_id'] == 'GO_01_01_001' ? (_chatResult()['topics'] as List) : <Object>[],
        'suggestion': o['attention']['level'] == 'high'
            ? 'Add a worked example, then revisit Week01-LectureA.pptx.'
            : null,
      });
    }
    return _error('Not found', 'HTTPError', 404);
  }

  Map<String, dynamic> _chatResult() => {
    'ran_at': '2026-09-25T10:00:00+00:00',
    'kind': 'simulated',
    'model': 'gpt-4o-mini',
    'questions': 90,
    'agreement': 0.87,
    'topics': [
      {
        'label': 'Why do we subtract the gradient?',
        'go_id': 'GO_01_01_001',
        'students': 11,
        'questions': 14,
        'paraphrases': ['why is it minus the gradient'],
      },
    ],
  };

  // ------------------------------------------------------------------ audit state
  Map<String, dynamic>? auditRun;
  final decisions = <String, Map<String, dynamic>>{};
  int auditRuns = 0;

  /// What the next audit run finds.
  List<Map<String, dynamic>> nextFindings = [
    finding(
      'k1',
      'accessibility',
      'high',
      '12 picture(s) in Week04-LectureB.pptx have no text alternative',
      'well_supported',
    ),
    finding(
      'k2',
      'coverage',
      'medium',
      '“Implement gradient descent” has weak support in the materials',
      'experimental',
    ),
    finding('k3', 'bloom', 'low', 'Week 5 is mostly “Understand”', 'moderate'),
  ];

  static Map<String, dynamic> finding(String key, String check, String severity, String title, String tier) => {
    'key': key,
    'check': check,
    'severity': severity,
    'title': title,
    'explanation': 'Why $title matters.',
    'evidence': 'Evidence for $key',
    'target': {'kind': 'file', 'ref': 'x'},
    'tier': tier,
    'llm': false,
    'weight': 1,
    'status': 'open',
    'note': '',
    'new': false,
  };

  // ------------------------------------------------------------------ admin state
  final users = <Map<String, dynamic>>[
    user('alex.m', 'Alex M.', 'admin', owned: ['AIML101']),
    user('okafor', 'Dr Okafor', 'teacher', owned: ['AIML101']),
    user('slee', 'Sam Lee', 'student'),
    user('alex.m.preview', 'alex.m (preview)', 'student', kind: 'test'),
  ];
  final owners = <String, List<String>>{
    'AIML101': ['alex.m', 'okafor'],
  };

  static Map<String, dynamic> user(
    String name,
    String full,
    String role, {
    List<String> owned = const [],
    String kind = 'real',
  }) => {
    'username': name,
    'full_name': full,
    'role': role,
    'active': true,
    'session_kind': kind,
    'created_at': 'now',
    'enrolled_courses': <String>[],
    'owned_courses': owned,
  };

  // ------------------------------------------------------------------ preview state
  String? previewToken;
  final explanations = <Map<String, dynamic>>[];

  static List<Map<String, dynamic>> kcRows() => [
    kcRow(
      'GO_01_01_001',
      1,
      'LO_01_01',
      'Explain what AI is and how the Turing test defines intelligence',
      'Define AI',
      0.7,
    ),
    kcRow(
      'GO_01_01_002',
      1,
      'LO_01_01',
      'Explain what AI is and how the Turing test defines intelligence',
      'Turing test',
      0.75,
    ),
    kcRow('GO_02_02_001', 2, 'LO_02_02', 'Describe how a perceptron learns from its errors', 'Perceptron rule', 0.8),
    kcRow(
      'GO_02_02_002',
      2,
      'LO_02_02',
      'Describe how a perceptron learns from its errors',
      'Linear separability',
      0.85,
      similarity: 0.3,
    ),
  ];

  static Map<String, dynamic> kcRow(
    String id,
    int week,
    String lo,
    String loTitle,
    String name,
    double threshold, {
    double similarity = 0.7,
  }) => {
    'go_id': id,
    'week': week,
    'week_title': 'Week $week',
    'lo_id': lo,
    'lo_title': loTitle,
    'lo_short_title': '',
    'skill_name': name,
    'description': 'About $name',
    'cognitive_level': 'Understand',
    'mastery_threshold': threshold,
    'keywords': ['k1'],
    'prerequisites': <String>[],
    'prerequisite_notes': <String>[],
    'split_from': null,
    'merged_from': <String>[],
    'provenance': {
      'source_file': 'Week0$week-LectureA-Notes.md',
      'excerpt': 'An excerpt about $name',
      'similarity': similarity,
    },
  };

  http.Response _json(Object? body, [int status = 200]) =>
      http.Response(jsonEncode(body), status, headers: {'content-type': 'application/json'});
  http.Response _error(String detail, String code, int status) => _json({'detail': detail, 'code': code}, status);

  Map<String, dynamic> _course(String code) => courses.firstWhere((c) => c['code'] == code);

  Future<http.Response> handle(http.Request request) async {
    requests.add(request);
    final path = request.url.path;
    final method = request.method;
    final body = request.body.isEmpty ? null : jsonDecode(request.body);
    (bodies[path] ??= []).add(body);

    if (path.startsWith('/admin')) return _admin(path, method, body);
    if (path == '/teach/materials-folders' && method == 'GET') {
      return _json([for (final f in materialsFolders) {'name': f}]);
    }
    if (path == '/teach/courses' && method == 'GET') return _json(courses);
    if (path == '/teach/courses' && method == 'POST') {
      final b = body as Map<String, dynamic>;
      if (courses.any((c) => c['code'] == b['code'])) {
        return _error('${b['code']} already exists. Choose another code.', 'InvalidInput', 400);
      }
      courses.add(course(b['code'] as String, b['name'] as String, managed: true, weeks: b['weeks'] as int));
      return _json({...b, 'created_by': 'alex.m', 'created_at': '2026-09-25T10:00:00+00:00'}, 201);
    }
    final m = RegExp(r'^/teach/courses/([^/]+)(/.*)?$').firstMatch(path);
    if (m != null) {
      final code = m.group(1)!;
      final rest = m.group(2) ?? '';
      if (!courses.any((c) => c['code'] == code)) return _error("You don't teach this course.", 'NotPermitted', 403);
      return _course_(code, rest, method, body, request);
    }
    final j = RegExp(r'^/teach/jobs/([^/]+)(/confirm|/cancel)?$').firstMatch(path);
    if (j != null) {
      final job = jobs[j.group(1)];
      if (job == null) return _error('No such job.', 'NotFound', 404);
      if (j.group(2) == '/confirm') job['status'] = 'queued';
      if (j.group(2) == '/cancel') job['status'] = 'cancelled';
      if (j.group(2) == '/cancel') _course(job['course'] as String)['active_job'] = null;
      return _json(job);
    }
    return _error('Not found', 'HTTPError', 404);
  }

  Future<http.Response> _course_(String code, String rest, String method, Object? body, http.Request request) async {
    switch ((method, rest)) {
      case ('GET', ''):
        return _json(_course(code));
      case ('GET', '/objectives'):
        final plan = plans[code];
        return plan == null ? _error('No learning objectives yet.', 'NotFound', 404) : _json(plan);
      case ('PUT', '/objectives'):
        final weeks = (body as Map<String, dynamic>)['weeks'] as List;
        if (weeks.any((w) => ((w as Map)['objectives'] as List).isEmpty)) {
          return _error('Week 2 needs 1 to 12 learning objectives.', 'InvalidInput', 400);
        }
        plans[code] = {'weeks': weeks, 'updated_by': 'alex.m', 'updated_at': 'now'};
        return _json(plans[code]);
      case ('GET', '/uploads'):
        return _json(uploads[code] ?? const []);
      case ('GET', '/materials-source'):
        return _json(materialsSources[code]);
      case ('POST', '/materials-source'):
        final b = body as Map<String, dynamic>;
        materialsSources[code] = {'type': b['type'], 'path': b['path']};
        return _json(materialsSources[code], 201);
      case ('DELETE', '/materials-source'):
        materialsSources[code] = null;
        return http.Response('', 204);
      case ('GET', '/materials-source/sync-preview'):
        final entries = syncPreviewEntries[code] ?? const [];
        final counts = {
          for (final s in ['new', 'changed', 'unchanged', 'removed', 'rejected'])
            s: entries.where((e) => e['status'] == s).length,
        };
        return _json({'entries': entries, ...counts});
      case ('GET', '/jobs'):
        return _json([
          for (final job in jobs.values)
            if (job['course'] == code) job,
        ]);
      case ('POST', '/jobs'):
        if (_course(code)['active_job'] != null) {
          return _error('This course already has a job. Wait for it to finish, or cancel it.', 'Busy', 409);
        }
        final id = 'job${++_jobs}';
        jobs[id] = job(id, code);
        _course(code)['active_job'] = id;
        return _json(jobs[id], 201);
      case ('GET', '/kc'):
        final draft = drafts[code];
        return _json({
          'published_version': published.containsKey(code) ? publishedVersion : null,
          'versions': [
            if (published.containsKey(code))
              {'version': publishedVersion, 'live': true, 'objectives': published[code]!.length},
          ],
          'draft': draft == null ? null : {'source': draft['source'], 'saves': draft['saves']},
        });
      case ('POST', '/kc/draft'):
        if (drafts.containsKey(code) && (body as Map)['replace'] != true) {
          return _error('This course already has a draft. Keep editing it, or replace it.', 'WrongState', 409);
        }
        drafts[code] = _draft(code, [for (final r in published[code] ?? kcRows()) Map<String, dynamic>.of(r)]);
        return _json(drafts[code], 201);
      case ('GET', '/kc/draft'):
        return drafts[code] == null ? _error("There's no draft.", 'NotFound', 404) : _json(drafts[code]);
      case ('PUT', '/kc/draft'):
        final rows = [
          for (final r in (body as Map)['rows'] as List) Map<String, dynamic>.of(r as Map<String, dynamic>),
        ];
        final bad = rows.where((r) => (r['mastery_threshold'] as num) > 0.95).toList();
        if (bad.isNotEmpty) {
          return _error(
            "The draft wasn't saved: row ${rows.indexOf(bad.first) + 1}: Mastery threshold must be 0.5 to 0.95.",
            'InvalidInput',
            400,
          );
        }
        var next = 3;
        for (final r in rows) {
          r['go_id'] ??= 'GO_0${r['week']}_0${r['week']}_00${next++}';
        }
        final saves = (drafts[code]?['saves'] as int? ?? 0) + 1;
        drafts[code] = {..._draft(code, rows), 'saves': saves};
        return _json(drafts[code]);
      case ('DELETE', '/kc/draft'):
        drafts.remove(code);
        return http.Response('', 204);
      case ('POST', '/kc/draft/validate'):
        final rows = (body as Map)['rows'] as List;
        return _json({
          'issues': _issues([for (final r in rows) r as Map<String, dynamic>]),
        });
      case ('GET', '/kc/draft/export'):
        return http.Response.bytes(
          utf8.encode('xlsx-bytes'),
          200,
          headers: {'content-type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'},
        );
      case ('GET', '/kc/diff'):
        return _json(_diff(code));
      case ('POST', '/kc/publish'):
        final draft = drafts.remove(code)!;
        published[code] = [for (final r in draft['rows'] as List) r as Map<String, dynamic>];
        publishedVersion += 1;
        _course(code)['has_kc_model'] = true;
        return _json({
          'version': publishedVersion,
          'changes': {'changed': 1},
          'impact': {},
          'mastery_records_migrated': 0,
        });
      case ('GET', '/audit'):
        return _json(auditRun == null ? null : _withDecisions(auditRun!));
      case ('GET', '/audit/estimate'):
        return _json({'usd': 0.002, 'objectives': 63, 'notes': <String>[]});
      case ('POST', '/audit/runs'):
        final before = {for (final f in (auditRun?['findings'] as List? ?? const [])) (f as Map)['key']};
        final now = [
          for (final f in nextFindings) {...f, 'new': auditRun != null && !before.contains(f['key'])},
        ];
        final resolved = [
          for (final f in (auditRun?['findings'] as List? ?? const []))
            if (!now.any((n) => n['key'] == (f as Map)['key'])) {'key': (f as Map)['key'], 'title': f['title']},
        ];
        auditRun = {
          'id': 'run${++auditRuns}',
          'course': code,
          'kc_version': publishedVersion,
          'ran_at': '2026-09-25T10:00:00+00:00',
          'ran_by': 'alex.m',
          'counts': <String, int>{},
          'total': now.length,
          'reviewed': 0,
          'skipped': <String>[],
          'findings': now,
          'resolved_since_last': resolved,
        };
        return _json(_withDecisions(auditRun!), 201);
      case ('POST', '/preview'):
        previewToken = 'preview-token-$code';
        return _json({
          'username': 'alex.m.preview',
          'token': previewToken,
          'course': code,
          'version': publishedVersion,
          'expires_at': '2026-09-25T22:00:00+00:00',
        });
      case ('POST', '/preview/reset'):
        explanations.clear();
        return http.Response('', 204);
      case ('GET', '/preview/explain'):
        return _json(explanations);
      case ('GET', '/preview/probes'):
        return _json([
          {'id': 'diagnostic', 'text': 'Answer the tutor\'s first question with "I don\'t know"'},
          {'id': 'hint', 'text': 'Ask for a hint instead of answering'},
        ]);
    }
    if (rest.startsWith('/analytics')) return _analytics(rest, method, request);
    if (rest.startsWith('/videos')) return _videos(code, rest, method, body);
    final decide = RegExp(r'^/audit/findings/(.+)$').firstMatch(rest);
    if (method == 'PUT' && decide != null) {
      final key = decide.group(1)!;
      final b = body as Map<String, dynamic>;
      if (b['status'] == 'open') {
        decisions.remove(key);
      } else {
        decisions[key] = {'status': b['status'], 'note': b['note'] ?? ''};
      }
      final f = (auditRun!['findings'] as List).cast<Map<String, dynamic>>().firstWhere((x) => x['key'] == key);
      return _json({...f, ...?decisions[key]});
    }
    final del = RegExp(r'^/uploads/(.+)$').firstMatch(rest);
    if (method == 'DELETE' && del != null) {
      final name = Uri.decodeComponent(del.group(1)!);
      uploads[code]?.removeWhere((u) => u['name'] == name);
      return http.Response('', 204);
    }
    return _error('Not found', 'HTTPError', 404);
  }

  Map<String, dynamic> _withDecisions(Map<String, dynamic> run) {
    final findings = [
      for (final f in run['findings'] as List) {...f as Map<String, dynamic>, ...?decisions[f['key']]},
    ];
    return {...run, 'findings': findings, 'reviewed': findings.where((f) => f['status'] != 'open').length};
  }

  http.Response _admin(String path, String method, Object? body) {
    if (path == '/admin/users' && method == 'GET') return _json(users);
    if (path == '/admin/users' && method == 'POST') {
      final b = body as Map<String, dynamic>;
      if (users.any((u) => u['username'] == b['username'])) {
        return _error('That username is taken. Choose another.', 'InvalidInput', 400);
      }
      final u = user(b['username'] as String, b['full_name'] as String, b['role'] as String);
      users.add(u);
      return _json(u, 201);
    }
    final uc = RegExp(r'^/admin/users/([^/]+)/courses/([^/]+)$').firstMatch(path);
    if (uc != null && (method == 'PUT' || method == 'DELETE')) {
      final account = users.firstWhere((x) => x['username'] == uc.group(1), orElse: () => const {});
      if (account.isEmpty) return _error('No account called ${uc.group(1)}.', 'NotFound', 404);
      final enrolled = List<String>.from(account['enrolled_courses'] as List);
      if (method == 'PUT') {
        if (!enrolled.contains(uc.group(2))) enrolled.add(uc.group(2)!);
      } else {
        enrolled.remove(uc.group(2));
      }
      account['enrolled_courses'] = enrolled;
      return _json(account);
    }
    final u = RegExp(r'^/admin/users/(.+)$').firstMatch(path);
    if (u != null && method == 'PATCH') {
      final account = users.firstWhere((x) => x['username'] == u.group(1));
      final b = body as Map<String, dynamic>;
      if (b['role'] != null) account['role'] = b['role'];
      if (b['active'] != null) account['active'] = b['active'];
      if (b['session_kind'] != null) account['session_kind'] = b['session_kind'];
      return _json(account);
    }
    final o = RegExp(r'^/admin/courses/([^/]+)/owners(?:/(.+))?$').firstMatch(path);
    if (o != null) {
      final list = owners[o.group(1)!] ??= [];
      if (method == 'PUT') list.add(o.group(2)!);
      if (method == 'DELETE') list.remove(o.group(2));
      return _json({'course': o.group(1), 'owners': list});
    }
    return _error('Not found', 'HTTPError', 404);
  }

  /// `POST .../uploads` (multipart).
  Future<http.Response> handleMultipart(http.BaseRequest request, List<int> bytes) async {
    requests.add(request);
    final imp = RegExp(r'^/teach/courses/([^/]+)/kc/draft/import$').firstMatch(request.url.path);
    if (imp != null) {
      final code = imp.group(1)!;
      final rows = [for (final r in published[code] ?? kcRows()) Map<String, dynamic>.of(r)];
      rows.first['mastery_threshold'] = 0.9;
      drafts[code] = {..._draft(code, rows), 'source': 'import', 'saves': 1};
      return _json({'draft': drafts[code], 'diff': _diff(code)});
    }
    final m = RegExp(r'^/teach/courses/([^/]+)/uploads$').firstMatch(request.url.path);
    if (m == null) return _error('Not found', 'HTTPError', 404);
    final code = m.group(1)!;
    final text = latin1.decode(bytes);
    final names = RegExp(r'filename="([^"]+)"').allMatches(text).map((x) => x.group(1)!).toList();
    final week = RegExp(r'name="week"\r\n\r\n(\d+)').firstMatch(text)?.group(1);
    if (names.any((n) => n.endsWith('.exe'))) {
      return _error(
        'run.exe: LEA takes PDF, Word, PowerPoint, Excel, Markdown, text, notebook, MP3, MP4 and WAV files.',
        'InvalidInput',
        400,
      );
    }
    final added = [
      for (final n in names)
        {
          'name': n,
          'size': 1200,
          'sha256': 'x',
          'week': week == null ? null : int.parse(week),
          'kind': null,
          'uploaded_by': 'alex.m',
          'uploaded_at': 'now',
        },
    ];
    final list = uploads[code] ??= [];
    list
      ..removeWhere((u) => names.contains(u['name']))
      ..addAll(added);
    _course(code)['uploads'] = list.length;
    return _json(added, 201);
  }

  Map<String, dynamic> job(String id, String code, {String status = 'awaiting_confirmation'}) => {
    'id': id,
    'course': code,
    'status': status,
    'step': '',
    'step_label': '',
    'percent': 0,
    'steps': ['convert', 'transcribe', 'embed', 'kc_draft', 'profile', 'verify'],
    'estimate': {
      'usd': 0.41,
      'per_step': {'convert': 0, 'transcribe': 0, 'embed': 0.3, 'kc_draft': 0.11, 'profile': 0, 'verify': 0},
      'files': 3,
      'documents': 2,
      'media': 1,
      'images': 4,
      'model_calls': 5,
      'notes': ['1 audio/video file(s) are transcribed on this PC with Whisper: no OpenAI cost.'],
    },
    'result': <String, dynamic>{},
    'error': null,
    'created_by': 'alex.m',
    'created_at': 'now',
    'started_at': null,
    'finished_at': null,
    'log': ['10:00:00 Estimated OpenAI cost: \$0.41. Waiting for confirmation.'],
  };

  Map<String, dynamic> _draft(String code, List<Map<String, dynamic>> rows) => {
    'course': code,
    'source': 'published',
    'based_on': published.containsKey(code) ? publishedVersion : null,
    'created_by': 'alex.m',
    'created_at': 'now',
    'updated_by': 'alex.m',
    'updated_at': '2026-09-25T10:00:00+00:00',
    'saves': 0,
    'rows': rows,
    'issues': _issues(rows),
  };

  List<Map<String, dynamic>> _issues(List<Map<String, dynamic>> rows) => [
    for (final (i, r) in rows.indexed)
      if ((r['similarity'] ?? (r['provenance'] as Map?)?['similarity'] ?? 1) as num < 0.4)
        {'row': i + 1, 'field': 'provenance', 'message': 'Weak support in the course content.', 'level': 'warning'},
    for (final (i, r) in rows.indexed)
      if ((r['mastery_threshold'] as num) > 0.95)
        {
          'row': i + 1,
          'field': 'mastery_threshold',
          'message': 'Mastery threshold must be 0.5 to 0.95.',
          'level': 'error',
        },
  ];

  Map<String, dynamic> _diff(String code) {
    final before = {for (final r in published[code] ?? const <Map<String, dynamic>>[]) r['go_id']: r};
    final after = {for (final r in (drafts[code]?['rows'] as List? ?? const [])) (r as Map)['go_id']: r};
    final changed = [
      for (final id in after.keys)
        if (before.containsKey(id) && before[id]!['mastery_threshold'] != after[id]!['mastery_threshold'])
          {
            'go_id': id,
            'changes': [
              {
                'field': 'mastery_threshold',
                'before': before[id]!['mastery_threshold'],
                'after': after[id]!['mastery_threshold'],
              },
            ],
          },
    ];
    final added = [
      for (final id in after.keys)
        if (!before.containsKey(id)) {'go_id': id, 'skill_name': after[id]!['skill_name'], 'week': after[id]!['week']},
    ];
    final retired = [
      for (final id in before.keys)
        if (!after.containsKey(id)) {'go_id': id, 'skill_name': before[id]!['skill_name']},
    ];
    return {
      'added': added,
      'changed': changed,
      'retired': retired,
      'splits': <Object>[],
      'merges': <Object>[],
      'counts': {
        'added': added.length,
        'changed': changed.length,
        'removed': retired.length,
        'splits': 0,
        'merges': 0,
        'total': after.length,
      },
      'impact': {
        'students_affected': retired.isEmpty ? 0 : 3,
        'students_with_mastery': 12,
        'with_mastery_on': {'retired': retired.isEmpty ? 0 : 3, 'split': 0, 'merged': 0},
      },
    };
  }
}
