String formatBytes(int bytes) {
  if (bytes < 1024) return '$bytes B';
  if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
  return '${(bytes / (1024 * 1024)).toStringAsFixed(2)} MB';
}

String endpointFilename(String endpoint) => switch (endpoint) {
  'split-all' || 'pdf-to-images' => '$endpoint.zip',
  'info' => 'info.json',
  _ => '$endpoint.pdf',
};
