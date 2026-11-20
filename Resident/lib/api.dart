import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

// Which server the app talks to, chosen when you build or run:
//   Emulator (default):  flutter run                      -> http://10.0.2.2:8000
//   Phone over USB:      adb reverse tcp:8000 tcp:8000
//                        flutter run --dart-define=API_URL=http://localhost:8000
//   Real users:          flutter build apk --release --dart-define=API_URL=https://your-domain
// Release builds refuse plain http:// so sign-in codes and tokens are always encrypted in transit.
const String kBaseUrl = String.fromEnvironment('API_URL', defaultValue: 'http://10.0.2.2:8000');
const _tokenKey = 'proplink_token';
const _timeout = Duration(seconds: 20);

class ApiException implements Exception {
  final String message;
  ApiException(this.message);
  @override
  String toString() => message;
}

class Api {
  // Stored with Android Keystore encryption, not in plain shared preferences.
  static const _store = FlutterSecureStorage();
  static String? token;
  static final ValueNotifier<bool> authed = ValueNotifier(false);

  static String? get configProblem => kReleaseMode && !kBaseUrl.startsWith('https://')
      ? 'This build is not set up for a secure (https) server. Rebuild with --dart-define=API_URL=https://...'
      : null;

  static Future<void> loadToken() async {
    try {
      token = await _store.read(key: _tokenKey);
    } catch (_) {
      token = null; // storage unreadable (e.g. after a device restore): just sign in again
    }
    authed.value = token != null;
  }

  static Future<void> saveToken(String? t) async {
    token = t;
    try {
      if (t == null) {
        await _store.delete(key: _tokenKey);
      } else {
        await _store.write(key: _tokenKey, value: t);
      }
    } catch (_) {}
    authed.value = t != null;
  }

  static Future<void> signOut() async {
    try {
      await post('/me/logout');
    } catch (_) {}
    await saveToken(null);
  }

  static Future<dynamic> _send(String method, String path, [Object? body]) async {
    final problem = configProblem;
    if (problem != null) throw ApiException(problem);
    final uri = Uri.parse('$kBaseUrl/api$path');
    final headers = <String, String>{
      'Content-Type': 'application/json',
      if (token != null) 'Authorization': 'Bearer $token',
    };
    try {
      final http.Response r = await (method == 'POST'
              ? http.post(uri, headers: headers, body: body == null ? null : jsonEncode(body))
              : http.get(uri, headers: headers))
          .timeout(_timeout);
      final dynamic data = r.body.isEmpty ? null : jsonDecode(r.body);
      if (r.statusCode == 401) {
        await saveToken(null);
        throw ApiException('Please sign in again');
      }
      if (r.statusCode >= 400) {
        final detail = data is Map ? data['detail'] : null;
        throw ApiException(detail is String
            ? detail
            : r.statusCode == 422
                ? 'Please check what you entered'
                : 'Request failed');
      }
      return data;
    } on ApiException {
      rethrow;
    } on TimeoutException {
      throw ApiException('The server took too long to answer. Check your connection.');
    } catch (_) {
      throw ApiException('Cannot reach the server');
    }
  }

  static Future<dynamic> get(String path) => _send('GET', path);
  static Future<dynamic> post(String path, [Object? body]) => _send('POST', path, body);
}