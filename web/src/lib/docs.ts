import type { DocSummary } from "@/lib/api";

function looksLikeTempName(name: string) {
  const base = name.replace(/\.pdf$/i, "").trim();
  return /^tmp/i.test(base) || /^[a-f0-9]{16}$/i.test(base);
}

/** Prefer the uploaded filename over PDF metadata / temp paths. */
export function formatDocName(doc: DocSummary | null | undefined): string {
  if (!doc) return "Document Q&A";
  const source = String(doc.source_name || doc.filename || "").trim();
  const title = String(doc.title || "").trim();
  if (source && !looksLikeTempName(source)) {
    return source.replace(/\.pdf$/i, "") || source;
  }
  if (title && !looksLikeTempName(title)) {
    return title.replace(/\.pdf$/i, "") || title;
  }
  if (source) return source.replace(/\.pdf$/i, "") || source;
  if (title) return title;
  return doc.doc_id;
}
