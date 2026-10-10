class PageRanges {
  static List<int> parse(String spec, int pageCount) {
    if (pageCount < 1 || spec.trim().isEmpty) {
      throw const FormatException('Enter a page range.');
    }
    final result = <int>[];
    for (final raw in spec.split(',')) {
      final part = raw.trim();
      if (part.isEmpty) throw const FormatException('Empty page range segment.');
      final range = part.split('-');
      if (range.length == 1) {
        final page = int.tryParse(range.first.trim());
        if (page == null || page < 1 || page > pageCount) {
          throw FormatException('Page must be between 1 and $pageCount.');
        }
        result.add(page);
      } else if (range.length == 2) {
        final first = int.tryParse(range[0].trim());
        final last = int.tryParse(range[1].trim());
        if (first == null || last == null || first < 1 || last < first || last > pageCount) {
          throw FormatException('Invalid range. Pages must be between 1 and $pageCount.');
        }
        result.addAll(List<int>.generate(last - first + 1, (i) => first + i));
      } else {
        throw const FormatException('Use ranges like 1-3,5,8-10.');
      }
    }
    if (result.toSet().length != result.length) {
      throw const FormatException('Duplicate pages are not allowed.');
    }
    return result;
  }
}
