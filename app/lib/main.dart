import 'dart:io';
import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'core/api_client.dart';
import 'core/settings.dart';
import 'features/settings_screen.dart';
import 'features/tool_screen.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  try { final temp=await getTemporaryDirectory(); for(final entity in temp.listSync()) { if(entity is File && entity.path.contains('private-pdf-')) { await entity.delete(); } } } catch (_) { }
  runApp(PrivatePdfApp(settings:AppSettings()));
}

class PrivatePdfApp extends StatelessWidget {
  const PrivatePdfApp({super.key,required this.settings});
  final AppSettings settings;
  @override Widget build(BuildContext context) {
    final api=ApiClient(settings);
    return MaterialApp(title:'Private PDF Toolkit',debugShowCheckedModeBanner:false,theme:ThemeData(colorScheme:ColorScheme.fromSeed(seedColor:const Color(0xff3157a4),brightness:Brightness.light),useMaterial3:true),darkTheme:ThemeData(colorScheme:ColorScheme.fromSeed(seedColor:const Color(0xff9ab7ff),brightness:Brightness.dark),useMaterial3:true),themeMode:ThemeMode.system,home:HomeScreen(settings:settings,api:api));
  }
}

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key,required this.settings,required this.api});
  final AppSettings settings; final ApiClient api;
  @override State<HomeScreen> createState()=>_HomeScreenState();
}
class _HomeScreenState extends State<HomeScreen> {
  bool _configured=false;
  @override void initState(){super.initState();_check();}
  Future<void> _check() async {final value=await widget.settings.configured;if(mounted)setState(()=>_configured=value);}
  Future<void> _settings() async {await Navigator.push(context,MaterialPageRoute(builder:(_)=>SettingsScreen(settings:widget.settings,api:widget.api)));_check();}
  @override Widget build(BuildContext context)=>Scaffold(appBar:AppBar(title:const Text('Private PDF Toolkit'),actions:[IconButton(tooltip:'Settings',onPressed:_settings,icon:const Icon(Icons.settings))]),body:ListView(padding:const EdgeInsets.all(16),children:[
    if(!_configured) Card(color:Theme.of(context).colorScheme.errorContainer,child:ListTile(leading:const Icon(Icons.warning_amber),title:const Text('Configure your server'),subtitle:const Text('Set your server URL and API key before processing files.'),trailing:const Icon(Icons.chevron_right),onTap:_settings)),
    for(final group in ['Organize','Convert','Optimize','Security','Utilities']) ...[
      Padding(padding:const EdgeInsets.fromLTRB(0,18,0,8),child:Text(group,style:Theme.of(context).textTheme.titleLarge)),
      GridView.count(shrinkWrap:true,physics:const NeverScrollableScrollPhysics(),crossAxisCount:2,mainAxisSpacing:10,crossAxisSpacing:10,childAspectRatio:1.25,children:[for(final tool in toolDefinitions.where((t)=>t.group==group)) Card(clipBehavior:Clip.antiAlias,child:InkWell(onTap:()=>Navigator.push(context,MaterialPageRoute(builder:(_)=>ToolScreen(definition:tool,api:widget.api))),child:Padding(padding:const EdgeInsets.all(14),child:Column(crossAxisAlignment:CrossAxisAlignment.start,mainAxisAlignment:MainAxisAlignment.center,children:[Icon(tool.icon,size:30,color:Theme.of(context).colorScheme.primary),const SizedBox(height:8),Text(tool.title,style:Theme.of(context).textTheme.titleMedium),const SizedBox(height:3),Text(tool.description,maxLines:2,overflow:TextOverflow.ellipsis,style:Theme.of(context).textTheme.bodySmall)]))))]),
    ],
  ]));
}
