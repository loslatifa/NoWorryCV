(function installExperienceParagraphs(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ExperienceParagraphs = api;
})(typeof globalThis === "object" ? globalThis : this, function experienceParagraphs() {
  function displayText(value) {
    return String(value || "").split(/\r?\n/).map(line => line
      .replace(/^\s*(?:[-•●▪‣]\s+|\d+[.)、]\s+)/, "")
      .trim()).filter(Boolean).join(" ");
  }

  function compose(facts) {
    let text = "";
    const segments = [];
    for (const fact of facts) {
      const content = displayText(fact.text);
      if (!content) continue;
      if (text) {
        if (/[。！？；]$/.test(text)) text += "";
        else if (/[.!?;:]$/.test(text)) text += " ";
        else text += /[\u4e00-\u9fff]/.test(text + content) ? "；" : ". ";
      }
      const start = text.length;
      text += content;
      segments.push({ factId: fact.id, start, end: text.length, text: content });
    }
    return { text, segments };
  }

  function canonical(value) {
    return Array.from(displayText(value)).filter((char, index, chars) =>
      /[\p{L}\p{N}%+/#@_-]/u.test(char)
      || (char === "." && /[\p{L}\p{N}]/u.test(chars[index - 1] || "") && /[\p{L}\p{N}]/u.test(chars[index + 1] || ""))
    ).join("");
  }

  function paragraphFor(facts, saved) {
    const composed = compose(facts);
    return saved && canonical(saved) === canonical(composed.text) ? saved : composed.text;
  }

  function splitChangedText(value) {
    const text = displayText(value).replace(/^[\s。；;!?！？,，:：]+/, "").replace(/^\.(?!\d)\s*/, "");
    const pieces = [];
    let start = 0;
    let depth = 0;
    for (let index = 0; index < text.length; index += 1) {
      const char = text[index];
      if ("（([{".includes(char)) depth += 1;
      if ("）)]}".includes(char)) depth = Math.max(0, depth - 1);
      const chineseEnd = /[。！？；]/.test(char);
      const englishEnd = /[.!?;]/.test(char) && (!text[index + 1] || /\s/.test(text[index + 1]));
      if (depth || (!chineseEnd && !englishEnd)) continue;
      const prefix = text.slice(start, index + 1);
      if (char === "." && /(?:\b(?:Mr|Mrs|Ms|Dr|Prof|Inc|Ltd|Co|Corp|Sr|Jr|vs|etc)\.|\b(?:[A-Za-z]\.){2,})$/i.test(prefix)) continue;
      const piece = prefix.trim();
      if (/[\p{L}\p{N}]/u.test(piece)) pieces.push(piece);
      start = index + 1;
    }
    const tail = text.slice(start).trim();
    if (/[\p{L}\p{N}]/u.test(tail)) pieces.push(tail);
    return pieces;
  }

  function reconcile(facts, value, { kind, ownerId, createId }) {
    const text = displayText(value);
    const original = compose(facts);
    if (text === original.text) return facts.map(fact => ({ ...fact }));
    const anchors = [];
    const boundary = char => !char || /[\s。！？.!?；;，,:：()（）\[\]{}]/.test(char);
    // Longer facts are matched first so a short phrase cannot claim part of another fact.
    const candidates = original.segments.map((segment, index) => ({ ...segment, index }))
      .sort((a, b) => b.text.length - a.text.length || a.index - b.index);
    for (const segment of candidates) {
      const needle = segment.text.replace(/[。！？；;!?]+$/, "");
      if (!needle) continue;
      let position = text.indexOf(needle);
      while (position !== -1) {
        const end = position + needle.length;
        if (boundary(text[position - 1]) && boundary(text[end])
            && !anchors.some(anchor => position < anchor.end && end > anchor.start)) {
          let consumed = end;
          if (/[。！？；;!?]$/.test(segment.text) && text[end] === segment.text.at(-1)) consumed += 1;
          anchors.push({ start: position, end: consumed, fact: facts.find(fact => fact.id === segment.factId) });
          break;
        }
        position = text.indexOf(needle, position + 1);
      }
    }
    anchors.sort((a, b) => a.start - b.start);
    const kept = new Set(anchors.map(anchor => anchor.fact.id));
    const replaced = facts.filter(fact => !kept.has(fact.id)).map(fact => fact.id);
    const result = [];
    const addChanged = fragment => {
      splitChangedText(fragment).forEach(content => {
        const id = createId();
        result.push({ id, category: kind === "projects" ? "project_bullet" : "work_bullet",
          text: content, source_type: "user", source_span: `${kind}.${ownerId}.bullets.${id}`,
          source_excerpt: content, evidence_level: "user_confirmed", confidence: 1,
          confirmed: false, allowed_operations: ["rewrite", "reorder", "highlight"],
          replaces_fact_ids: replaced,
        });
      });
    };
    let cursor = 0;
    for (const anchor of anchors) {
      addChanged(text.slice(cursor, anchor.start));
      result.push({ ...anchor.fact });
      cursor = anchor.end;
    }
    addChanged(text.slice(cursor));
    return result;
  }

  return { compose, displayText, canonical, paragraphFor, reconcile, splitChangedText };
});
