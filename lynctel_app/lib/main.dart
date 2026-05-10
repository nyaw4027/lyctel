import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

// --- MOCK PROVIDERS (Replace these with your actual logic files later) ---
class AuthProvider with ChangeNotifier {
  bool isLoggedIn = false;
  void init() { /* Check for saved tokens here */ }
}

class CartProvider with ChangeNotifier {
  List items = [];
  int get itemCount => items.length;
}

class ProductProvider with ChangeNotifier {
  List products = []; // Will fetch from Django/Firebase later
}

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(
    MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => AuthProvider()..init()),
        ChangeNotifierProvider(create: (_) => CartProvider()),
        ChangeNotifierProvider(create: (_) => ProductProvider()),
      ],
      child: const LynctelMarketplace(),
    ),
  );
}

class LynctelMarketplace extends StatelessWidget {
  const LynctelMarketplace({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'Lynctel Market',
      theme: ThemeData(
        useMaterial3: true,
        colorSchemeSeed: Colors.orange, // Standard "Market" vibe
      ),
      home: const MainShell(),
    );
  }
}

class MainShell extends StatefulWidget {
  const MainShell({super.key});
  @override
  State<MainShell> createState() => _MainShellState();
}

class _MainShellState extends State<MainShell> {
  int _selectedIndex = 0;

  final List<Widget> _pages = [
    const Center(child: Text("Browse Products")),
    const Center(child: Text("Your Cart")),
    const Center(child: Text("Your Account")),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text("LYNCTEL MARKET"),
        centerTitle: true,
        actions: [
          IconButton(onPressed: () {}, icon: const Icon(Icons.search)),
        ],
      ),
      body: _pages[_selectedIndex],
      bottomNavigationBar: NavigationBar(
        selectedIndex: _selectedIndex,
        onDestinationSelected: (index) => setState(() => _selectedIndex = index),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.store), label: 'Shop'),
          NavigationDestination(icon: Icon(Icons.shopping_cart), label: 'Cart'),
          NavigationDestination(icon: Icon(Icons.person), label: 'Profile'),
        ],
      ),
    );
  }
}