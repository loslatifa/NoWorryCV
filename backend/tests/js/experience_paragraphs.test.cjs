const test = require('node:test');
const assert = require('node:assert/strict');
const { compose, reconcile, canonical, paragraphFor, splitChangedText } = require('../../app/static/experience_paragraphs.js');

test('one paragraph retains all original facts and their identities', () => {
  const facts = [
    {id:'a',text:'- 使用 SQL 分析转化漏斗'},
    {id:'b',text:'2. 设计 A/B Testing，转化率提升 3.5%'},
    {id:'c',text:'完成 Power BI 看板。'},
    {id:'d',text:'维护 CI/CD 与 Next.js 交付流程'},
    {id:'e',text:'通过 C++ 完成数据处理'},
  ];
  const original = structuredClone(facts);
  const result = compose(facts);
  assert.equal(result.segments.length, 5);
  assert.deepEqual(result.segments.map(item => item.factId), ['a','b','c','d','e']);
  assert(!result.text.includes('\n'));
  assert(!result.text.startsWith('-'));
  for (const term of ['SQL', 'A/B Testing', '3.5%', 'Power BI', 'CI/CD', 'Next.js', 'C++']) assert(result.text.includes(term));
  for (const segment of result.segments) assert.equal(result.text.slice(segment.start, segment.end), segment.text);
  assert.deepEqual(facts, original);
});

test('display merging leaves English abbreviations and numeric values intact', () => {
  const result = compose([
    {id:'en1',text:'Worked with Acme Inc. on v2.1, improving results by 12.5%.'},
    {id:'en2',text:'Delivered CI/CD and A/B Testing with the U.S. team.'},
  ]);
  assert.equal(result.segments.length, 2);
  assert(result.text.includes('Inc. on v2.1'));
  assert(result.text.includes('12.5%'));
  assert(result.text.includes('U.S. team.'));
});

test('separate calls never mix experiences and empty descriptions stay empty', () => {
  assert.equal(compose([]).text, '');
  assert.equal(compose([{id:'first',text:'第一段工作'}]).text, '第一段工作');
  assert.equal(compose([{id:'second',text:'第二段项目'}]).text, '第二段项目');
});

function options(kind='work_experiences', ownerId='work-a') {
  let sequence=0;
  return {kind,ownerId,createId:()=>`new-${++sequence}`};
}

test('only edited points are rebuilt; unedited source IDs and provenance survive', () => {
  const facts = ['使用 SQL 分析数据','通过 A/B Testing 提升转化率 3.5%','维护 Power BI 看板','部署 CI/CD 流程','使用 C++ 处理数据'].map((text,index)=>({id:`fact-${index}`,text,source_type:'resume',source_excerpt:text,source_span:`work_experiences.work-a.bullets.${index}`}));
  const paragraph=compose(facts).text.replace('3.5%','5.5%');
  const result=reconcile(facts,paragraph,options());
  assert.deepEqual(result.filter(f=>f.source_type==='resume').map(f=>f.id),['fact-0','fact-2','fact-3','fact-4']);
  const edited=result.find(f=>f.source_type==='user');
  assert(edited.text.includes('5.5%'));
  assert(!edited.text.includes('3.5%'));
  assert.equal(edited.source_excerpt,edited.text);
  assert.deepEqual(edited.replaces_fact_ids,['fact-1']);
  assert.equal(canonical(compose(result).text),canonical(paragraph));
});

test('deleting and reordering points keeps remaining IDs without cross-assigning', () => {
  const facts=[{id:'a',text:'负责数据分析'},{id:'b',text:'负责交付协调'},{id:'c',text:'维护监控'}];
  assert.deepEqual(reconcile(facts,'维护监控；负责数据分析',options()).map(f=>f.id),['c','a']);
  const project=reconcile([], '使用 Python 分析数据。交付数据看板。',options('projects','project-b'));
  assert.equal(project.length,2);
  assert(project.every(f=>f.source_span.startsWith('projects.project-b.bullets.')));
});

test('duplicates and overlapping phrases retain separate, correct identities', () => {
  const facts=[{id:'long',text:'负责数据分析并维护看板'},{id:'short',text:'负责数据分析'},{id:'copy',text:'负责数据分析'}];
  const result=reconcile(facts,'负责数据分析；负责数据分析并维护看板；负责数据分析',options());
  assert.deepEqual(result.map(f=>f.id),['short','long','copy']);
  const extended=reconcile([{id:'old',text:'使用 SQL'}],'使用 SQLAlchemy 完成交付',options());
  assert(extended.every(f=>f.id!=='old'));
});

test('sentence splitting protects numbers, versions, abbreviations and compound skills', () => {
  const value='Worked with Acme Inc. and the U.S. team on Next.js v2.1, improving results by 12.5%. Delivered CI/CD and A/B Testing.';
  const parts=splitChangedText(value);
  assert.equal(parts.length,2);
  assert.equal(parts.join(' '),value);
  assert.equal(canonical('v2.1'), 'v2.1');
  assert.notEqual(canonical('v2.1'),canonical('v21'));
  assert.equal(paragraphFor([{id:'a',text:'提升 3.5%'}],'提升 13.5%'),'提升 3.5%');
});
