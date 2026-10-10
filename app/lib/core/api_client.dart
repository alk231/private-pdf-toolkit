import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import 'settings.dart';

class ApiException implements Exception {
  ApiException(this.message, {this.statusCode});
  final String message;
  final int? statusCode;
  @override
  String toString() => message;
}

class ApiResult {
  const ApiResult({required this.bytes, required this.filename, this.headers = const {}});
  final List<int> bytes;
  final String filename;
  final Map<String, String> headers;
}

class ApiClient {
  ApiClient(this.settings);
  final AppSettings settings;
  http.Client? _activeClient;
  void cancel() { _activeClient?.close(); _activeClient = null; }
  static const timeout = Duration(minutes: 5);

  Future<Map<String, String>> _headers() async => {'X-API-Key': await settings.apiKey};
  Future<Uri> _uri(String path) async {
    final base = await settings.serverUrl;
    if (base.isEmpty) throw ApiException('Set the server URL in Settings.');
    return Uri.parse('$base/$path');
  }

  Future<bool> testConnection() async {
    try {
      final response = await http.get(await _uri('health')).timeout(const Duration(seconds: 12));
      if (response.statusCode != 200) throw ApiException('Health check returned HTTP ${response.statusCode}.', statusCode: response.statusCode);
      return true;
    } on ApiException { rethrow; } catch (_) { throw ApiException('Could not connect to the server. Check URL, HTTPS, DNS, and firewall.'); }
  }

  Future<Map<String, dynamic>> info(File file, {void Function(double)? onProgress}) async {
    final response = await _upload('info', {'file': file}, {}, onProgress: onProgress, jsonResponse: true);
    return jsonDecode(utf8.decode(response.bytes)) as Map<String, dynamic>;
  }

  Future<ApiResult> upload(String endpoint, Map<String, File> files, {Map<String, String> fields = const {}, void Function(double)? onProgress}) =>
      _upload(endpoint, files, fields, onProgress: onProgress);

  Future<ApiResult> uploadMany(String endpoint, List<File> files, {String field = 'files', Map<String, String> fields = const {}, void Function(double)? onProgress}) {
    final map = <String, File>{};
    for (var i = 0; i < files.length; i++) { map['$field#$i'] = files[i]; }
    return _upload(endpoint, map, fields, onProgress: onProgress, repeatedField: field);
  }

  Future<ApiResult> _upload(String endpoint, Map<String, File> files, Map<String, String> fields, {void Function(double)? onProgress, bool jsonResponse = false, String? repeatedField}) async {
    final request = _ProgressMultipartRequest('POST', await _uri(endpoint));
    request.headers.addAll(await _headers());
    request.fields.addAll(fields);
    for (final entry in files.entries) {
      final field = repeatedField == null ? entry.key : repeatedField;
      request.files.add(await http.MultipartFile.fromPath(field, entry.value.path));
    }
    request.onProgress = onProgress;
    try {
      final client = http.Client();
      _activeClient = client;
      final streamed = await client.send(request).timeout(timeout);
      final response = await http.Response.fromStream(streamed).timeout(timeout);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        String message = 'Server request failed (HTTP ${response.statusCode}).';
        try { final data = jsonDecode(response.body); if (data is Map && data['error'] is String) message = data['error'] as String; } catch (_) { }
        throw ApiException(message, statusCode: response.statusCode);
      }
      if (jsonResponse) return ApiResult(bytes: response.bodyBytes, filename: 'info.json', headers: response.headers);
      final disposition = response.headers['content-disposition'] ?? '';
      final match = RegExp(r'filename="?([^";]+)').firstMatch(disposition);
      return ApiResult(bytes: response.bodyBytes, filename: match?.group(1) ?? (endpoint.contains('zip') || endpoint == 'split-all' || endpoint == 'pdf-to-images' ? '$endpoint.zip' : '$endpoint.pdf'), headers: response.headers);
    } on ApiException { rethrow; } on TimeoutException { throw ApiException('The request timed out. Try a smaller file or check server logs.'); } on SocketException { throw ApiException('Network connection failed. Check the configured server URL.'); } catch (_) { throw ApiException('Upload or download failed. Check your connection and server URL.'); } finally { _activeClient?.close(); _activeClient = null; }
  }
}

class _ProgressMultipartRequest extends http.MultipartRequest {
  _ProgressMultipartRequest(super.method, super.url);
  void Function(double)? onProgress;
  @override
  http.ByteStream finalize() {
    final stream = super.finalize();
    final total = contentLength;
    var sent = 0;
    final monitored = stream.transform(StreamTransformer<List<int>, List<int>>.fromHandlers(handleData: (chunk, sink) {
      sent += chunk.length;
      if (total > 0) onProgress?.call(sent / total);
      sink.add(chunk);
    }));
    return http.ByteStream(monitored);
  }
}
