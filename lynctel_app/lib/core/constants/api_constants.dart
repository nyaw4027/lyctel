class ApiConstants {
  // Use your IP address so both Web and Mobile can see the Django server
  static const String baseUrl = 'http://192.168.x.x:8000';

  // Auth Endpoints
  static const String login = '$baseUrl/accounts/login/';
  static const String register = '$baseUrl/accounts/register/';
  static const String profile = '$baseUrl/accounts/profile/';

  // Marketplace Endpoints
  static const String products = '$baseUrl/products/';
  static const String cart = '$baseUrl/cart/';
  static const String orders = '$baseUrl/orders/';

  // Headers
  static Map<String, String> headers(String? token) => {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    if (token != null) 'Authorization': 'Token $token',
  };
}