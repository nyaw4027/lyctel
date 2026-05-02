import 'package:flutter/material.dart';

void main() {
  runApp(const LynctelApp());
}

class LynctelApp extends StatelessWidget {
  const LynctelApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'Lynctel App',
      home: const HomePage(),
    );
  }
}

class HomePage extends StatelessWidget {
  const HomePage({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Lynctel Dashboard'),
      ),
      body: const Center(
        child: Text(
          'Welcome to Lynctel 🚀',
          style: TextStyle(fontSize: 20),
        ),
      ),
    );
  }
}