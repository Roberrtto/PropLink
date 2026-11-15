import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

// Android emulator reaches your PC at 10.0.2.2. For a real phone run:
//   adb reverse tcp:8000 tcp:8000
// and start the app with: flutter run --dart-define=API_URL=http://localhost:8000
const String kBaseUrl = String.fromEnvironment('API_URL', defaultValue: 'http://10.0.2.2:8000');

class ApiException implements Exception {
  final String message;
  ApiException(this.message);
  @override
  String toString() => message;
}

class Api {
  static String? token;
  static final ValueNotifier<bool> authed = ValueNotifier(false);

  static Future<void> loadToken() async {
    final p = await SharedPreferences.getInstance();
    token = p.getString('token');
    authed.value = token != null;
  }

  static Future<void> saveToken(String? t) async {
    token = t;
    final p = await SharedPreferences.getInstance();
    if (t == null) {
      await p.remove('token');
    } else {
      await p.setString('token', t);
    }
    authed.value = t != null;
  }

  static Future<dynamic> _send(String method, String path, [Object? body]) async {
    final uri = Uri.parse('$kBaseUrl/api$path');
    final headers = <String, String>{
      'Content-Type': 'application/json',
      if (token != null) 'Authorization': 'Bearer $token',
    };
    try {
      final http.Response r = method == 'POST'
          ? await http.post(uri, headers: headers, body: body == null ? null : jsonEncode(body))
          : await http.get(uri, headers: headers);
      final dynamic data = r.body.isEmpty ? null : jsonDecode(r.body);
      if (r.statusCode == 401) {
        await saveToken(null);
        throw ApiException('Please sign in again');
      }
      if (r.statusCode >= 400) {
        throw ApiException(data is Map && data['detail'] is String ? data['detail'] as String : 'Request failed');
      }
      return data;
    } on ApiException {
      rethrow;
    } catch (_) {
      throw ApiException('Cannot reach the server');
    }
  }

  static Future<dynamic> get(String path) => _send('GET', path);
  static Future<dynamic> post(String path, [Object? body]) => _send('POST', path, body);
}