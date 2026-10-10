import 'package:flutter_test/flutter_test.dart';
import 'package:private_pdf_toolkit/core/page_ranges.dart';

void main(){
  test('parses page ranges',(){expect(PageRanges.parse('1-3,5,8-10',10),[1,2,3,5,8,9,10]);});
  test('rejects out of range, duplicate and malformed input',(){for(final input in ['0','3-2','1,1','11','a','1,,2']){expect(()=>PageRanges.parse(input,10),throwsFormatException);}});
}
