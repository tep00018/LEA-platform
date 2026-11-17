import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers.dart';
import 'video_models.dart';

String _base(String code) => '/teach/courses/$code/videos';

/// Every objective with its videos, what a stuck student gets, and the state of automatic search.
final videosProvider = FutureProvider.autoDispose.family<VideosOverview, String>((ref, code) async {
  if (ref.watch(authProvider.select((s) => s.token)) == null) throw StateError('Not signed in');
  return VideosOverview.fromJson(await ref.watch(apiClientProvider).getObject(_base(code)));
});

/// Adds a video (LEA checks the link with YouTube). Throws [ApiError] with a message for the screen.
Future<CuratedVideo> addVideo(WidgetRef ref, String code, String goId, String url, String note) async {
  final json = await ref.read(apiClientProvider).postObject(_base(code), {'go_id': goId, 'url': url, 'note': note});
  ref.invalidate(videosProvider(code));
  return CuratedVideo.fromJson(json);
}

Future<void> removeVideo(WidgetRef ref, String code, String goId, String videoId) async {
  await ref.read(apiClientProvider).delete('${_base(code)}/$goId/$videoId');
  ref.invalidate(videosProvider(code));
}

/// Moves a video up or down; the order is the order students see.
Future<void> moveVideo(WidgetRef ref, String code, String goId, String videoId, {required bool up}) async {
  await ref.read(apiClientProvider).post('${_base(code)}/$goId/$videoId/move', {'direction': up ? 'up' : 'down'});
  ref.invalidate(videosProvider(code));
}
