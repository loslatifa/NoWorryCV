const {test} = require('node:test');
const assert = require('node:assert/strict');
const {parser} = require('../../app/static/progress_stream.js');
test('SSE framing survives arbitrary byte and line boundaries, comments and multi-line data', () => {
  const events=[]; const consume=parser(event=>events.push(event));
  const bytes=new TextEncoder().encode(': ping\r\nid: 1\r\nevent: status\r\ndata: {"message":"解析中"}\r\n\r\nevent: end\ndata: one\ndata: two\n\n');
  const decoder=new TextDecoder();
  for(const byte of bytes)consume(decoder.decode(Uint8Array.of(byte), {stream:true}));
  assert.deepEqual(events,[{event:'status',data:'{"message":"解析中"}'},{event:'end',data:'one\ntwo'}]);
});
