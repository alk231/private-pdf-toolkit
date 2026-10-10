import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:private_pdf_toolkit/core/api_client.dart';
import 'package:private_pdf_toolkit/core/settings.dart';
import 'package:private_pdf_toolkit/features/settings_screen.dart';

class FakeSettings extends AppSettings {
  String url=''; String key='';
  @override Future<String> get serverUrl async=>url;
  @override Future<String> get apiKey async=>key;
  @override Future<bool> get configured async=>url.isNotEmpty&&key.isNotEmpty;
  @override Future<void> save({required String url,required String key}) async {this.url=url;this.key=key;}
}
void main(){testWidgets('settings screen exposes URL, key and connection test', (tester) async {final settings=FakeSettings();await tester.pumpWidget(MaterialApp(home:SettingsScreen(settings:settings,api:ApiClient(settings))));await tester.pumpAndSettle();expect(find.text('Server URL'),findsOneWidget);expect(find.text('API key'),findsOneWidget);expect(find.text('Test connection'),findsOneWidget);});}
