import 'dart:async';
import 'dart:io';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import '../core/api_client.dart';
import '../core/format_utils.dart';
import '../core/page_ranges.dart';
import '../core/widgets/tool_scaffold.dart';

class ToolDefinition {
  const ToolDefinition(this.id, this.title, this.description, this.icon, this.group, {this.images = false, this.multiple = false});
  final String id, title, description, group;
  final IconData icon;
  final bool images, multiple;
}

const toolDefinitions = <ToolDefinition>[
  ToolDefinition('merge','Merge PDFs','Combine multiple PDF files in upload order.',Icons.call_merge,'Organize',multiple:true),
  ToolDefinition('split','Split PDF','Extract selected pages into one PDF.',Icons.content_cut,'Organize'),
  ToolDefinition('split-all','Split all pages','Create one PDF per page in a ZIP.',Icons.library_books,'Organize'),
  ToolDefinition('organize','Organize pages','Reorder pages and remove omitted pages.',Icons.reorder,'Organize'),
  ToolDefinition('rotate','Rotate PDF','Rotate all pages or selected pages.',Icons.rotate_90_degrees_ccw,'Organize'),
  ToolDefinition('page-numbers','Page numbers','Add page numbers to the bottom.',Icons.format_list_numbered,'Organize'),
  ToolDefinition('images-to-pdf','Images to PDF','Convert photos to A4 PDF pages.',Icons.image,'Convert',images:true,multiple:true),
  ToolDefinition('pdf-to-images','PDF to images','Render each page into a ZIP.',Icons.photo_library,'Convert'),
  ToolDefinition('office-to-pdf','Office to PDF','Convert office documents on your server.',Icons.description,'Convert'),
  ToolDefinition('compress','Compress PDF','Reduce PDF size using Ghostscript.',Icons.compress,'Optimize'),
  ToolDefinition('ocr','OCR PDF','Make scanned PDFs searchable.',Icons.document_scanner,'Optimize'),
  ToolDefinition('protect','Protect PDF','Encrypt with a password.',Icons.lock,'Security'),
  ToolDefinition('unlock','Unlock PDF','Remove PDF password protection.',Icons.lock_open,'Security'),
  ToolDefinition('watermark','Watermark','Apply text watermark to every page.',Icons.branding_watermark,'Security'),
  ToolDefinition('info','PDF info','Read page count, file size and encryption status.',Icons.info_outline,'Utilities'),
];

class ToolScreen extends StatefulWidget {
  const ToolScreen({super.key, required this.definition, required this.api});
  final ToolDefinition definition;
  final ApiClient api;
  @override State<ToolScreen> createState() => _ToolScreenState();
}

class _ToolScreenState extends State<ToolScreen> {
  final _picker = ImagePicker();
  final List<File> _files = [];
  final _pages = TextEditingController();
  final _order = TextEditingController();
  final _password = TextEditingController();
  final _confirm = TextEditingController();
  final _watermark = TextEditingController(text: 'PRIVATE');
  bool _busy = false, _cancelled = false;
  double _progress = 0;
  int? _pageCount;
  List<int> _pageOrder = [];
  String _level = 'medium', _language = 'eng', _format = 'png', _position = 'bottom-center', _watermarkPosition = 'diagonal';
  int _degrees = 90, _start = 1, _dpi = 150;
  double _opacity = .25;

  @override void dispose() { _pages.dispose(); _order.dispose(); _password.dispose(); _confirm.dispose(); _watermark.dispose(); super.dispose(); }

  Future<void> _pick({bool many = false, bool images = false}) async {
    try {
      if (images) {
        final result = await FilePicker.platform.pickFiles(type: FileType.image, allowMultiple: many, withData: false);
        if (result != null) setState(() { _files.addAll(result.files.where((f) => f.path != null).map((f) => File(f.path!))); });
      } else {
        final type = widget.definition.id == 'office-to-pdf' ? FileType.custom : FileType.custom;
        final result = await FilePicker.platform.pickFiles(type: type, allowedExtensions: widget.definition.id == 'office-to-pdf' ? ['doc','docx','xls','xlsx','ppt','pptx','odt','rtf','txt'] : ['pdf'], allowMultiple: many, withData: false);
        if (result != null) {
          final picked = result.files.where((f) => f.path != null).map((f) => File(f.path!)).toList();
          setState(() { _files.addAll(picked); _pageCount = null; });
          if (picked.isNotEmpty && widget.definition.id != 'office-to-pdf' && widget.definition.id != 'merge') await _loadInfo(picked.first);
        }
      }
    } catch (e) { _showError(e.toString()); }
  }

  Future<void> _camera() async {
    try { final x = await _picker.pickImage(source: ImageSource.camera); if (x != null) setState(() => _files.add(File(x.path))); }
    catch (e) { _showError('Camera unavailable: $e'); }
  }

  Future<void> _loadInfo(File file) async {
    try { final data = await widget.api.info(file); if (mounted) setState(() { _pageCount = data['pages'] as int?; _pageOrder = List<int>.generate(_pageCount ?? 0, (i) => i + 1); }); }
    catch (e) { _showError(e.toString()); }
  }

  void _showError(String message) { if (!mounted) return; ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message))); }
  void _cancel() { _cancelled = true; widget.api.cancel(); if (mounted) setState(() { _busy = false; }); }

  Map<String,String> _fields() {
    switch (widget.definition.id) {
      case 'split': PageRanges.parse(_pages.text, _pageCount ?? 0); return {'pages':_pages.text.trim()};
      case 'organize': return {'order': _pageOrder.isNotEmpty ? _pageOrder.join(',') : _order.text.trim()};
      case 'rotate': if (_pages.text.trim().isNotEmpty) PageRanges.parse(_pages.text, _pageCount ?? 0); return {'degrees':'$_degrees','pages':_pages.text.trim()};
      case 'page-numbers': return {'position':_position,'start':'$_start'};
      case 'protect': if (_password.text.isEmpty || _password.text != _confirm.text) throw const FormatException('Enter matching non-empty passwords.'); return {'password':_password.text};
      case 'unlock': if (_password.text.isEmpty) throw const FormatException('Enter the PDF password.'); return {'password':_password.text};
      case 'watermark': return {'text':_watermark.text,'opacity':'$_opacity','position':_watermarkPosition};
      case 'compress': return {'level':_level};
      case 'ocr': return {'lang':_language};
      case 'pdf-to-images': return {'format':_format,'dpi':'$_dpi'};
      default: return {};
    }
  }

  Future<void> _run() async {
    if (_files.isEmpty) { _showError('Choose a file first.'); return; }
    if (widget.definition.id == 'merge' && _files.length < 2) { _showError('Choose at least two PDFs.'); return; }
    if (widget.definition.id == 'images-to-pdf' && _files.length > 50) { _showError('Choose no more than 50 images.'); return; }
    try {
      final fields = _fields();
      setState(() { _busy = true; _progress = 0; _cancelled = false; });
      final id = widget.definition.id;
      final ApiResult result;
      if (id == 'merge' || id == 'images-to-pdf') {
        result = await widget.api.uploadMany(id, _files, fields: fields, onProgress: (v) { if (mounted && !_cancelled) setState(() => _progress = v); });
      } else {
        result = await widget.api.upload(id, {'file':_files.first}, fields: fields, onProgress: (v) { if (mounted && !_cancelled) setState(() => _progress = v); });
      }
      if (_cancelled || !mounted) return;
      final temp = await getTemporaryDirectory();
      final output = File('${temp.path}/private-pdf-${DateTime.now().microsecondsSinceEpoch}-${result.filename}');
      await output.writeAsBytes(result.bytes, flush: true);
      if (id == 'info') {
        final info = String.fromCharCodes(result.bytes);
        if (mounted) await showDialog<void>(context: context, builder: (ctx) => AlertDialog(title: const Text('PDF information'), content: SelectableText(info), actions: [TextButton(onPressed: ()=>Navigator.pop(ctx), child: const Text('Close'))]));
        await output.delete();
      } else {
        final details = id == 'compress' ? 'Original: ${formatBytes(_files.first.lengthSync())}\nResult: ${formatBytes(output.lengthSync())}\n${_files.first.lengthSync() > 0 ? (((_files.first.lengthSync() - output.lengthSync()) / _files.first.lengthSync()) * 100).toStringAsFixed(1) : '0.0'}% saved' : null;
        await ToolScaffold.showResult(context, file: output, filename: result.filename, details: details,
          onSave: () async { try { final saved = await FilePicker.platform.saveFile(fileName: result.filename, bytes: await output.readAsBytes()); if (saved != null && mounted) _showError('File saved.'); } catch (e) { if (mounted) _showError('Save failed: $e'); } finally { if (await output.exists()) await output.delete(); } },
          onShare: () async { await Share.shareXFiles([XFile(output.path, name: result.filename)]); if (await output.exists()) await output.delete(); });
        if (await output.exists()) await output.delete();
      }
    } catch (e) { _showError(e is FormatException ? e.message : e.toString()); }
    finally { if (mounted) setState(() { _busy = false; }); }
  }

  Widget _options() {
    final id=widget.definition.id;
    if (id=='split' || id=='rotate') return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text('Pages found: ${_pageCount ?? 'Choose a PDF'}'), TextField(controller:_pages, decoration: const InputDecoration(labelText:'Pages (e.g. 1-3,5)', hintText:'Leave blank for all pages on Rotate')), if(id=='rotate') DropdownButton<int>(value:_degrees, items:[90,180,270].map((v)=>DropdownMenuItem(value:v,child:Text('$v°'))).toList(), onChanged:(v)=>setState(()=>_degrees=v??90))]);
    if(id=='organize') return Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Text('Pages found: ${_pageCount ?? 'Choose a PDF'}'),const Text('Drag to reorder. Remove a page to delete it.'),ReorderableListView(shrinkWrap:true,physics:const NeverScrollableScrollPhysics(),onReorder:(oldIndex,newIndex)=>setState((){if(newIndex>oldIndex)newIndex--;final page=_pageOrder.removeAt(oldIndex);_pageOrder.insert(newIndex,page);}),children:[for(final page in _pageOrder) ListTile(key:ValueKey('page-$page'),leading:const Icon(Icons.drag_handle),title:Text('Page $page'),trailing:IconButton(tooltip:'Delete page',onPressed:()=>setState(()=>_pageOrder.remove(page)),icon:const Icon(Icons.delete_outline)))])]);
    if(id=='protect' || id=='unlock') return Column(children:[TextField(controller:_password,obscureText:true,decoration:InputDecoration(labelText:'Password',suffixIcon:const Icon(Icons.visibility_off))),if(id=='protect')TextField(controller:_confirm,obscureText:true,decoration:const InputDecoration(labelText:'Confirm password')),const SizedBox(height:8),const Text('A forgotten password cannot be recovered.',style:TextStyle(color:Colors.red))]);
    if(id=='compress') return DropdownButtonFormField<String>(value:_level,decoration:const InputDecoration(labelText:'Compression level'),items:const [DropdownMenuItem(value:'low',child:Text('Low (printer)')),DropdownMenuItem(value:'medium',child:Text('Medium (ebook)')),DropdownMenuItem(value:'high',child:Text('High (screen)'))],onChanged:(v)=>setState(()=>_level=v??'medium'));
    if(id=='ocr') return DropdownButtonFormField<String>(value:_language,decoration:const InputDecoration(labelText:'OCR language'),items:const [DropdownMenuItem(value:'eng',child:Text('English')),DropdownMenuItem(value:'hin',child:Text('Hindi')),DropdownMenuItem(value:'spa',child:Text('Spanish')),DropdownMenuItem(value:'fra',child:Text('French')),DropdownMenuItem(value:'deu',child:Text('German'))],onChanged:(v)=>setState(()=>_language=v??'eng'));
    if(id=='pdf-to-images') return Column(children:[DropdownButtonFormField<String>(value:_format,items:const [DropdownMenuItem(value:'png',child:Text('PNG')),DropdownMenuItem(value:'jpg',child:Text('JPG'))],onChanged:(v)=>setState(()=>_format=v??'png')),TextFormField(initialValue:'150',keyboardType:TextInputType.number,decoration:const InputDecoration(labelText:'DPI (36-600)'),onChanged:(v)=>_dpi=int.tryParse(v)??150)]);
    if(id=='page-numbers') return Column(children:[DropdownButtonFormField<String>(value:_position,items:const [DropdownMenuItem(value:'bottom-center',child:Text('Bottom center')),DropdownMenuItem(value:'bottom-right',child:Text('Bottom right'))],onChanged:(v)=>setState(()=>_position=v??'bottom-center')),TextFormField(initialValue:'1',keyboardType:TextInputType.number,decoration:const InputDecoration(labelText:'Start number'),onChanged:(v)=>_start=int.tryParse(v)??1)]);
    if(id=='watermark') return Column(children:[TextField(controller:_watermark,decoration:const InputDecoration(labelText:'Watermark text')),Slider(value:_opacity,min:.05,max:.8,divisions:15,label:_opacity.toStringAsFixed(2),onChanged:(v)=>setState(()=>_opacity=v)),Text('Opacity ${(_opacity*100).round()}%'),DropdownButtonFormField<String>(value:_watermarkPosition,items:const [DropdownMenuItem(value:'diagonal',child:Text('Diagonal')),DropdownMenuItem(value:'center',child:Text('Center'))],onChanged:(v)=>setState(()=>_watermarkPosition=v??'diagonal'))]);
    if(id=='split-all') return const Text('Every page will be placed in a ZIP archive.');
    return const SizedBox.shrink();
  }

  @override Widget build(BuildContext context) {
    final d=widget.definition;
    return ToolScaffold(title:d.title,busy:_busy,progress:_progress,onCancel:_cancel,child:Column(crossAxisAlignment:CrossAxisAlignment.stretch,children:[
      Icon(d.icon,size:48,color:Theme.of(context).colorScheme.primary),const SizedBox(height:8),Text(d.description,textAlign:TextAlign.center),const SizedBox(height:20),
      if (_files.isNotEmpty) ReorderableListView(shrinkWrap:true,physics:const NeverScrollableScrollPhysics(),onReorder:(a,b)=>setState(() {if(b>a)b--;final f=_files.removeAt(a);_files.insert(b,f);}),children:[for(var i=0;i<_files.length;i++) ListTile(key:ValueKey(_files[i].path),leading:d.images?Image.file(_files[i],width:42,height:42,fit:BoxFit.cover,errorBuilder:(_,__,___)=>const Icon(Icons.image)):const Icon(Icons.picture_as_pdf),title:Text(_files[i].uri.pathSegments.last,maxLines:1,overflow:TextOverflow.ellipsis),subtitle:Text(formatBytes(_files[i].lengthSync())),trailing:Row(mainAxisSize:MainAxisSize.min,children:[if(d.multiple) const Icon(Icons.drag_handle),IconButton(onPressed:()=>setState(()=>_files.removeAt(i)),icon:const Icon(Icons.close))]))]) else const Card(child:Padding(padding:EdgeInsets.all(20),child:Text('No files selected',textAlign:TextAlign.center))),
      if(['split','rotate','organize','protect','unlock','compress','ocr','pdf-to-images','page-numbers','watermark'].contains(d.id)) _options(),
      if(d.id=='images-to-pdf' || d.id=='merge') OutlinedButton.icon(onPressed:_busy?null:()=>_pick(many:true,images:d.images),icon:const Icon(Icons.add),label:const Text('Add files'))
      else FilledButton.tonalIcon(onPressed:_busy?null:()=>_pick(images:d.images),icon:const Icon(Icons.attach_file),label:const Text('Choose file')),
      if(d.images) OutlinedButton.icon(onPressed:_busy?null:_camera,icon:const Icon(Icons.camera_alt),label:const Text('Capture with camera')),
      const SizedBox(height:16),FilledButton.icon(onPressed:_busy?null:_run,icon:const Icon(Icons.play_arrow),label:Text(_busy?'Processing…':'Run ${d.title}')),
    ]));
  }
}
