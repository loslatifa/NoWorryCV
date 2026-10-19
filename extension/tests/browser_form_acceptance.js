async (page) => {
  await page.evaluate(() => {
    window.__formTestListeners = [];
    window.chrome = { runtime: { onMessage: { addListener(listener) { window.__formTestListeners.push(listener); } } } };
  });
  for (const name of ['form_controls.js', 'form_engine.js', 'content_script.js']) {
    await page.addScriptTag({ url: 'http://127.0.0.1:8765/extension/' + name + '?acceptance=' + Date.now() });
  }
  const result = await page.evaluate(async () => {
    const assert = (condition, message) => { if (!condition) throw new Error(message); };
    const send = message => new Promise(resolve => window.__formTestListeners.at(-1)(message, {}, resolve));
    const resume = {
      personal_info: { name: '合成候选人', email: 'synthetic@example.com', phone: '13800000000' }, summary: '合成介绍',
      education: [{ school: '合成大学', degree: '本科', start_date: '2024年6月' }],
      projects: [{ name: '合成项目', role: '开发', description: '已确认的合成项目描述', start_date: '2024.6', end_date: '至今' }]
    };
    const fields = (await send({ type: 'EXTRACT_FIELDS' })).fields;
    const preview = buildFillPreview(fields, resume);
    const year = preview.items.find(item => item.selector === '#education-start-year');
    const month = preview.items.find(item => item.selector === '#education-start-month');
    assert(year?.fill_value === '2024年' && year.enabled, 'year preview');
    assert(month?.fill_value === 'June' && month.enabled, 'month preview');
    const dateItems = preview.items.filter(item => item.field_type === 'month');
    assert(dateItems[0].fill_value === '2024-06' && dateItems[0].enabled, 'native month preview');
    assert(!dateItems[1].enabled && dateItems[1].notes.includes('精度'), 'present is manual');
    const filled = await send({ type: 'FILL_FIELDS', page_url: location.href, mappings: preview.items });
    assert(filled.failed_count === 0, 'valid fields fill without failure: ' + JSON.stringify(filled.results.filter(item => item.status === 'failed')));
    assert(document.querySelector('#degree').value === 'bachelor', 'degree alias');
    assert(document.querySelector('#education-start-year').value === 'year-2024', 'year selection');
    assert(document.querySelector('#education-start-month').value === '5', 'zero-based month selection');
    assert(document.querySelector('input[type=month]').value === '2024-06', 'native month fill');
    assert(document.querySelector('#submitted').textContent === '尚未提交', 'no submission');
    const undo = await send({ type: 'UNDO_LAST_FILL' });
    assert(undo.restored_count === filled.filled_count, 'undo complete');
    assert(document.querySelector('#degree').value === '' && document.querySelector('input[type=month]').value === '', 'undo raw original values');
    const fixtures = document.createElement('div');
    fixtures.innerHTML = '<label for="strict-date">录用日期</label><input id="strict-date" type="date" value="2020-01-01">' +
      '<label for="step-date">日期</label><input id="step-date" type="date" min="2024-06-01" step="7" value="2024-06-01">' +
      '<label for="city">城市</label><select id="city"><option value="keep">保留城市</option><option value="one">北京海淀</option><option value="two">北京朝阳</option></select>' +
      '<label for="disabled-degree">学历</label><select id="disabled-degree"><option value="keep">保留学历</option><optgroup label="停用" disabled><option value="b">本科</option></optgroup></select>' +
      '<label for="controlled">受控字段</label><input id="controlled" value="original">' +
      '<label for="invalid-select">无效选项</label><select id="invalid-select"><option value="keep">保留值</option><option value="b">本科</option></select>';
    document.querySelector('form').append(fixtures);
    const extracted = (await send({ type: 'EXTRACT_FIELDS' })).fields;
    assert(extracted.find(item => item.selector === '#disabled-degree').options.find(option => option.value === 'b').disabled, 'optgroup metadata');
    const manual = (selector, value) => ({ selector, fill_value: value, matched_resume_path: 'manual_override', enabled: true, confidence: 1 });
    document.querySelector('#invalid-select').setCustomValidity('站点要求人工检查');
    const failed = await send({ type: 'FILL_FIELDS', mappings: [manual('#strict-date', '2024-06'), manual('#step-date', '2024-06-03'), manual('#city', '北京'), manual('#disabled-degree', '本科'), manual('#invalid-select', '本科')] });
    assert(failed.failed_count === 5 && failed.filled_count === 0, 'unsupported values reported');
    assert(document.querySelector('#strict-date').value === '2020-01-01', 'missing day preserves old date');
    assert(document.querySelector('#step-date').value === '2024-06-01', 'invalid step preserves old date');
    assert(document.querySelector('#city').value === 'keep', 'no partial select guess');
    assert(document.querySelector('#disabled-degree').value === 'keep', 'no disabled option');
    assert(document.querySelector('#invalid-select').value === 'keep', 'invalid selection preserves original');
    const exactDate = await send({ type: 'FILL_FIELDS', mappings: [manual('#strict-date', '2024年6月15日')] });
    assert(exactDate.filled_count === 1 && document.querySelector('#strict-date').value === '2024-06-15', 'confirmed full date fills');
    const dateUndo = await send({ type: 'UNDO_LAST_FILL' });
    assert(dateUndo.restored_count === 1 && document.querySelector('#strict-date').value === '2020-01-01', 'date undo');
    document.querySelector('#controlled').addEventListener('input', event => setTimeout(() => { event.target.value = 'original'; }, 20));
    const reverted = await send({ type: 'FILL_FIELDS', mappings: [manual('#controlled', 'changed')] });
    assert(reverted.failed_count === 1 && reverted.results[0].reason.includes('重新渲染'), 'controlled rerender report');
    return { extracted_fields: fields.length, filled: filled.filled_count, restored: undo.restored_count, rejected: failed.failed_count, native_date_restored: dateUndo.restored_count, rerender_detected: reverted.failed_count, submitted: document.querySelector('#submitted').textContent };
  });
  return result;
}
