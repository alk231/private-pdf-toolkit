import 'dart:io';
import 'package:flutter/material.dart';
import '../format_utils.dart';

class ToolScaffold extends StatelessWidget {
  const ToolScaffold({super.key, required this.title, required this.busy, required this.progress, required this.onCancel, required this.child});
  final String title;
  final bool busy;
  final double progress;
  final VoidCallback onCancel;
  final Widget child;

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text(title)),
    body: SafeArea(child: Column(children: [
      if (busy) LinearProgressIndicator(value: progress > 0 && progress < 1 ? progress : null),
      if (busy) Padding(padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6), child: Row(children: [Expanded(child: Text('${(progress * 100).clamp(0, 100).round()}% uploaded')), TextButton.icon(onPressed: onCancel, icon: const Icon(Icons.cancel_outlined), label: const Text('Cancel'))])),
      Expanded(child: SingleChildScrollView(padding: const EdgeInsets.all(16), child: child)),
    ])),
  );

  static Future<void> showResult(BuildContext context, {required File file, required String filename, String? details, required VoidCallback onSave, required VoidCallback onShare}) async {
    if (!context.mounted) return;
    await showModalBottomSheet<void>(context: context, showDragHandle: true, builder: (ctx) => SafeArea(child: Padding(padding: const EdgeInsets.all(20), child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('Processing complete', style: Theme.of(ctx).textTheme.titleLarge), const SizedBox(height: 8),
      Text(filename, maxLines: 2, overflow: TextOverflow.ellipsis), Text(formatBytes(file.lengthSync()), style: Theme.of(ctx).textTheme.bodySmall), if (details != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(details)), const SizedBox(height: 16),
      Row(children: [Expanded(child: FilledButton.icon(onPressed: () { Navigator.pop(ctx); onSave(); }, icon: const Icon(Icons.save_alt), label: const Text('Save to device'))), const SizedBox(width: 8), Expanded(child: OutlinedButton.icon(onPressed: () { Navigator.pop(ctx); onShare(); }, icon: const Icon(Icons.share), label: const Text('Share')))]),
    ]))));
  }
}
