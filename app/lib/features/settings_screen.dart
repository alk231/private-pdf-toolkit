import 'package:flutter/material.dart';
import '../core/api_client.dart';
import '../core/settings.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key, required this.settings, required this.api});
  final AppSettings settings;
  final ApiClient api;
  @override State<SettingsScreen> createState() => _SettingsScreenState();
}
class _SettingsScreenState extends State<SettingsScreen> {
  final _url=TextEditingController(); final _key=TextEditingController();
  bool _obscure=true, _testing=false; String? _message; bool _warning=false;
  @override void initState(){super.initState();_load();}
  Future<void> _load() async { _url.text=await widget.settings.serverUrl; _key.text=await widget.settings.apiKey; if(mounted)setState(()=>_validate()); }
  void _validate(){final url=_url.text.trim();_warning=url.startsWith('http://');}
  bool get _validUrl { final u=_url.text.trim(); if(u.isEmpty)return false; final uri=Uri.tryParse(u); if(uri==null||!uri.hasAuthority)return false; if(uri.scheme=='https')return true; return uri.scheme=='http'&&RegExp(r'^http://(localhost|127\.0\.0\.1|10\.0\.2\.2|192\.168(?:\.\d{1,3}){2})(:\d+)?(?:/|$)').hasMatch(u); }
  Future<void> _save() async {if(!_validUrl||_key.text.trim().length<24){setState(()=>_message='Enter a valid server URL and an API key at least 24 characters long.');return;} await widget.settings.save(url:_url.text,key:_key.text);if(mounted)setState(()=>_message='Settings saved securely on this device.');}
  Future<void> _test() async {await _save();if(!_validUrl)return;setState(()=>_testing=true);try{await widget.api.testConnection();if(mounted)setState(()=>_message='Connection successful.');}catch(e){if(mounted)setState(()=>_message=e.toString());}finally{if(mounted)setState(()=>_testing=false);}}
  @override void dispose(){_url.dispose();_key.dispose();super.dispose();}
  @override Widget build(BuildContext context)=>Scaffold(appBar:AppBar(title:const Text('Settings')),body:ListView(padding:const EdgeInsets.all(20),children:[
    const Text('Your server',style:TextStyle(fontWeight:FontWeight.bold,fontSize:18)),const SizedBox(height:8),
    TextField(controller:_url,keyboardType:TextInputType.url,onChanged:(_)=>setState(_validate),decoration:const InputDecoration(labelText:'Server URL',hintText:'https://pdf.example.com',prefixIcon:Icon(Icons.dns))),
    if(_warning) const Padding(padding:EdgeInsets.only(top:8),child:Text('Warning: HTTP is unencrypted. Use HTTP only for a trusted local development server. Public servers must use HTTPS.',style:TextStyle(color:Colors.red))),
    const SizedBox(height:12),TextField(controller:_key,obscureText:_obscure,decoration:InputDecoration(labelText:'API key',prefixIcon:const Icon(Icons.key),suffixIcon:IconButton(onPressed:()=>setState(()=>_obscure=!_obscure),icon:Icon(_obscure?Icons.visibility:Icons.visibility_off)))),
    const SizedBox(height:20),FilledButton(onPressed:_testing?null:_save,child:const Text('Save settings')),const SizedBox(height:8),OutlinedButton.icon(onPressed:_testing?null:_test,icon:_testing?const SizedBox(width:16,height:16,child:CircularProgressIndicator(strokeWidth:2)):const Icon(Icons.wifi_tethering),label:const Text('Test connection')),
    if(_message!=null) Padding(padding:const EdgeInsets.only(top:12),child:Text(_message!)),const SizedBox(height:12),const Text('The app sends files only to the server URL entered here. Use a valid HTTPS certificate. API keys are stored with platform secure storage.'),
  ]));
}
