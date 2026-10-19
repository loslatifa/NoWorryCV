(function(root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.ProgressStream = factory();
})(globalThis, function() {
  // Incremental SSE framing. TextDecoder upstream preserves split UTF-8 characters.
  function parser(onEvent) {
    let pending = '', event = '', data = [];
    function line(value) {
      if (!value) {
        if (data.length) onEvent({event: event || 'message', data: data.join('\n')});
        event = ''; data = []; return;
      }
      if (value.startsWith(':')) return;
      const at = value.indexOf(':');
      const key = at < 0 ? value : value.slice(0, at);
      let content = at < 0 ? '' : value.slice(at + 1);
      if (content.startsWith(' ')) content = content.slice(1);
      if (key === 'event') event = content;
      if (key === 'data') data.push(content);
    }
    return chunk => {
      pending += chunk;
      let at;
      while ((at = pending.indexOf('\n')) >= 0) {
        line(pending.slice(0, at).replace(/\r$/, ''));
        pending = pending.slice(at + 1);
      }
    };
  }
  return {parser};
});
