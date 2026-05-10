import 'dart:convert';
import 'package:http/http.dart' as http;
import '../../core/constants/api_constants.dart';

class ProductProvider with ChangeNotifier {
  List _products = [];
  List get products => _products;
  bool isLoading = false;

  Future<void> fetchProducts() async {
    isLoading = true;
    notifyListeners();
    
    try {
      final response = await http.get(Uri.parse(ApiConstants.products));
      if (response.statusCode == 200) {
        _products = json.decode(response.body);
      }
    } catch (e) {
      print("Error fetching products: $e");
    }

    isLoading = false;
    notifyListeners();
  }
}