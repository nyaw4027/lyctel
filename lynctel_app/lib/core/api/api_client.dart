import 'dart:convert';
import 'package:http/http.dart' as http;

class ApiClient {
  // 10.0.2.2 is the special alias to your laptop's localhost from the Android Emulator
  static const String baseUrl = "http://10.0.2.2:8000/api";

  // GET Request
  Future<http.Response> get(String endpoint, {String? token}) async {
    final response = await http.get(
      Uri.parse('$baseUrl/$endpoint'),
      headers: {
        'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
      },
    );
    return response;
  }

  // POST Request
  Future<http.Response> post(String endpoint, Map<String, dynamic> body, {String? token}) async {
    final response = await http.post(
      Uri.parse('$baseUrl/$endpoint'),
      headers: {
        'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
      },
      body: jsonEncode(body),
    );
    return response;
  }
}