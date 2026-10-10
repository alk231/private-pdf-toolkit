import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class AppSettings {
  AppSettings([FlutterSecureStorage? storage]) : _storage = storage ?? const FlutterSecureStorage();
  final FlutterSecureStorage _storage;
  static const _urlKey = 'server_url';
  static const _apiKey = 'api_key';

  Future<String> get serverUrl async => (await _storage.read(key: _urlKey) ?? '').trim().replaceAll(RegExp(r'/+$'), '');
  Future<String> get apiKey async => await _storage.read(key: _apiKey) ?? '';
  Future<bool> get configured async => (await serverUrl).isNotEmpty && (await apiKey).isNotEmpty;
  Future<void> save({required String url, required String key}) async {
    await _storage.write(key: _urlKey, value: url.trim().replaceAll(RegExp(r'/+$'), ''));
    await _storage.write(key: _apiKey, value: key.trim());
  }
  Future<void> clear() async { await _storage.delete(key: _urlKey); await _storage.delete(key: _apiKey); }
}
