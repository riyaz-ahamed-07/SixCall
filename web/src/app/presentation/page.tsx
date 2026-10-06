"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useState, type CSSProperties } from "react";
import styles from "./presentation.module.css";

const titles = ["The challenge", "Architecture", "Discovery tools", "Evidence tools", "Engineering & results"];
const notes = [
  "We answer from a newly uploaded PDF with four permitted tools and at most six document calls. The custom harness enforces the budget using ContextVar. Citations are checked locally; insufficient evidence produces abstention. These are engineering strengths, not a measured advantage over competitors. Embedded document instructions are treated as untrusted data; injection resistance still needs held-out evaluation.",
  "Python handles ingestion, not the LLM. Parsed pages, a section tree, and the lexical indexes live in the store. Every evidence read crosses the tool wrapper. When a heading title already overlaps the question, the loop does not call a planner model: one answer call cites span ids. A weak outline may spend one TOC pick limited to existing titles and terms from the question.",
  "Both discovery tools return structure, never page bodies. Heading ranges end at the next heading of equal or higher rank. Examples are illustrative. list_documents is an available capability; a query with an already selected document usually starts with list_headings. Each invoked tool costs one slot.",
  "Keyword lookup returns only page numbers. get_page returns exactly one physical page. Six is a ceiling, not a target; executed failed attempts count. Calls without an active session are refused. Span ids have to exist on a fetched page. Summaries cover only the pages read within budget.",
  "pytest covers the budget, the section walk, supersede, absent questions, injection, repair, and zero-tool asks. Tool time and model time are logged separately on the CLI. Answer accuracy on unseen PDFs still has to be rehearsed live.",
];

function Flow({ steps }: { steps: string[] }) {
  return <div className={styles.flow}>{steps.map((step, i) => <div className={styles.flowItem} key={step}><span>{step}</span>{i < steps.length - 1 && <b aria-hidden="true">→</b>}</div>)}</div>;
}

function ToolDiagram({ kind }: { kind: "documents" | "headings" | "search" | "page" }) {
  const data = {
    documents: { left: "DOCUMENT STORE", input: "list_documents()", output: "Metadata only", rows: ["Robotics · 160 pages", "Policy · 42 pages", "Manual · 86 pages"] },
    headings: { left: "HEADING TREE", input: "list_headings(id)", output: "Titles + ranges", rows: ["1  Robotics", "↳ 1.1  Navigation", "   ↳ Path planning · 9–11"] },
    search: { left: "LEXICAL INDEX", input: '"path planning"', output: "Page numbers only", rows: ["keyword → page IDs", "[9, 12, 35, 37]", "No snippets or scores"] },
    page: { left: "PHYSICAL PAGES", input: "get_page(id, 9)", output: "One page of text", rows: ["7     8     [9]     10", "Path planning concerns…", "Evidence available to model"] },
  }[kind];
  return <svg viewBox="0 0 620 180" role="img" aria-label={`${data.input} returns ${data.output}`} className={styles.toolDiagram}>
    <rect x="2" y="12" width="198" height="150" rx="12" fill="#eef1ef" />
    <text x="20" y="39" fontSize="12" fill="#557069" letterSpacing="1">{data.left}</text>
    {data.rows.map((row, i) => <text key={row} x="20" y={70 + i * 29} fontSize="14" fill="#173d34">{row}</text>)}
    <path d="M210 88 H245 M235 81 L245 88 L235 95" fill="none" stroke="#159c83" strokeWidth="2" />
    <rect x="258" y="56" width="180" height="64" rx="32" fill="#153e34" />
    <text x="348" y="94" fontSize="13" textAnchor="middle" fill="white" fontFamily="monospace">{data.input}</text>
    <path d="M447 88 H480 M470 81 L480 88 L470 95" fill="none" stroke="#159c83" strokeWidth="2" />
    <text x="492" y="80" fontSize="13" fill="#173d34">{data.output.split(" ").slice(0, 2).join(" ")}</text>
    <text x="492" y="101" fontSize="13" fill="#173d34">{data.output.split(" ").slice(2).join(" ")}</text>
  </svg>;
}

function Tool({ number, name, type, description, code, kind }: { number: string; name: string; type: string; description: string; code: string; kind: "documents" | "headings" | "search" | "page" }) {
  return <article className={styles.tool}><div className={styles.toolTitle}><span>{number}</span><h2>{name}</h2></div><p>{description}</p><ToolDiagram kind={kind} /><div className={styles.codeLabel}><span>{type}</span><span>ILLUSTRATIVE OUTPUT</span></div><pre>{code}</pre></article>;
}

export default function Presentation() {
  const [slide, setSlide] = useState(0);
  const [showNotes, setShowNotes] = useState(false);
  const [image, setImage] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [scale, setScale] = useState(1);
  useEffect(() => {
    const resize = () => setScale(Math.min((window.innerWidth * 0.94) / 1280, (window.innerHeight - 140) / 720, 1.25));
    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  useEffect(() => {
    const handle = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setImage(null); setShowNotes(false); return; }
      if (image) return;
      if (["ArrowRight", "PageDown", " "].includes(event.key)) { event.preventDefault(); setSlide(s => Math.min(4, s + 1)); }
      if (["ArrowLeft", "PageUp"].includes(event.key)) { event.preventDefault(); setSlide(s => Math.max(0, s - 1)); }
      if (event.key === "Home") setSlide(0);
      if (event.key === "End") setSlide(4);
      if (event.key.toLowerCase() === "n") setShowNotes(n => !n);
      if (/^[1-5]$/.test(event.key)) setSlide(Number(event.key) - 1);
    };
    window.addEventListener("keydown", handle);
    return () => window.removeEventListener("keydown", handle);
  }, [image]);
  const fullscreen = async () => {
    try { if (document.fullscreenElement) await document.exitFullscreen(); else await document.documentElement.requestFullscreen(); }
    catch { setNotice("Fullscreen unavailable. Use your browser’s fullscreen shortcut."); }
  };
  return <main className={styles.deck} style={{ "--slide-scale": scale } as CSSProperties}>
    <header className={styles.toolbar}><Link href="/" className={styles.logo}>sixcall<span> / presentation</span></Link><div><button onClick={() => setShowNotes(n => !n)} aria-pressed={showNotes}>Presenter notes</button><button onClick={() => window.print()}>Print / PDF</button><button onClick={fullscreen}>Fullscreen ↗</button></div></header>
    <div className={styles.viewport}>
      <section className={`${styles.slide} ${styles.cover}`} hidden={slide !== 0} aria-label="Slide 1: Problem and solution">
        <div className={styles.eyebrow}>SIX-HOUR AI HACKATHON / SIXCALL</div>
        <div className={styles.coverGrid}><div><h1>Every call<br />has to <em>count.</em></h1><p className={styles.lead}>Answers from unseen PDFs.<br />Explicit budgets. Traceable evidence.</p><div className={styles.constraint}>4 tools · 6 calls · section tree · span ids</div></div><div className={styles.heroNumber}><span>6</span><p>document calls, maximum<br /><b>4 tools. One answer call on the happy path.</b></p><div className={styles.orbit}>PDF → EVIDENCE → ANSWER</div></div></div>
        <div className={styles.threeColumns}><div><label>01 / THE PROBLEM</label><p>Find the right evidence in an unfamiliar PDF under a strict call budget.</p></div><div><label>02 / OUR SOLUTION</label><p>Headings + literal keywords guide a small, custom Python harness.</p></div><div><label>03 / WHY THIS APPROACH</label><p>Enforced accounting, exact citations, visible traces and explicit abstention.</p></div></div>
      </section>
      <section className={styles.slide} hidden={slide !== 1} aria-label="Slide 2: System architecture">
        <div className={styles.eyebrow}>02 / SYSTEM DESIGN</div><h1>Two flows. One evidence boundary.</h1>
        <div className={styles.archGrid}><article><h2><span>A</span> Upload & store</h2><Flow steps={["PDF upload", "Validate", "PyMuPDF / OCR", "Normalize + index", "Document store"]} /><p>25 MB limit · PDF signature · SHA-256 identity · temporary file deleted</p><div className={styles.entities}>documents <b>·</b> pages <b>·</b> headings <b>·</b> lexical index</div><button className={styles.imageButton} onClick={() => setImage("/presentation/upload-architecture.jpg")}><Image src="/presentation/upload-architecture.jpg" width={1266} height={1006} alt="Supplied PDF ingestion architecture" /></button><button className={styles.textButton} onClick={() => setImage("/presentation/storage-workflow.png")}>Open detailed storage diagram ↗</button></article><article><h2><span>B</span> Ask & answer</h2><Flow steps={["Question", "Session + budget", "Plan + rank", "Read pages", "Generate + verify"]} /><p>Headings → keywords → scorer → page reads → evidence IDs</p><div className={styles.entities}>answer or abstention <b>·</b> quotes <b>·</b> tool trace</div><button className={styles.imageButton} onClick={() => setImage("/presentation/query-architecture.png")}><Image src="/presentation/query-architecture.png" width={1266} height={814} alt="Supplied question processing architecture" /></button><p className={styles.small}>One final generation; planner currently makes a separate model request.</p></article></div>
        <div className={styles.boundary}>Agent sees only permitted tool results. <span>Parsed content: local JSON + optional Postgres. Supplied diagrams depict earlier revisions; see notes.</span></div>
      </section>
      <section className={styles.slide} hidden={slide !== 2} aria-label="Slide 3: Discovery tools">
        <div className={styles.eyebrow}>03 / DISCOVERY</div><h1>Find the document. Map its structure.</h1><p className={styles.subtitle}>Two tools narrow the search without exposing page bodies.</p>
        <div className={styles.tools}><Tool number="01" name="list_documents()" type="list[DocumentMetadata]" description="Discover available documents through titles and metadata." kind="documents" code={'[\n  { "doc_id": "c81744f74e123abc",\n    "title": "Robotics",\n    "page_count": 160 }\n]'} /><Tool number="02" name="list_headings(doc_id)" type="list[Heading]" description="Read the heading tree and hierarchical page ranges." kind="headings" code={'[\n  { "title": "Path planning",\n    "level": 2,\n    "start": 9, "end": 11 }\n]'} /></div><div className={styles.bottomLine}>Metadata and headings only <span>Each invocation consumes one document-tool slot.</span></div>
      </section>
      <section className={styles.slide} hidden={slide !== 3} aria-label="Slide 4: Evidence tools">
        <div className={styles.eyebrow}>04 / EVIDENCE</div><h1>Locate pages. Read only what counts.</h1><p className={styles.subtitle}>Literal discovery first; document text enters through one-page reads.</p>
        <div className={styles.tools}><Tool number="03" name="search_keyword(id, keyword)" type="list[int]" description="Return matching page numbers, with no snippets or scores." kind="search" code={'search_keyword(id, "path planning")\n\n→ [9, 12, 35, 37]'} /><Tool number="04" name="get_page(id, page_number)" type="str" description="Fetch exactly one physical PDF page as extracted text." kind="page" code={'get_page(id, 9)\n\n→ "Path planning concerns finding\n   a collision-free route …"'} /></div><div className={styles.budget}><span><b>1</b> heading</span><i>+</i><span><b>2</b> searches</span><i>+</i><span><b>3</b> page reads</span><i>=</i><strong>6 / 6</strong><small>Then one final generation.<br />Six is a ceiling, not a target.</small></div>
      </section>
      <section className={styles.slide} hidden={slide !== 4} aria-label="Slide 5: Engineering and measurements">
        <div className={styles.eyebrow}>05 / ENGINEERING & VALIDATION</div><h1>Small orchestration. Inspectable decisions.</h1>
        <div className={styles.resultsGrid}><div><table className={styles.technology}><tbody>{[["PyMuPDF", "Page extraction, outlines, optional OCR"], ["NLTK", "Tokenization + bundled stopwords; preserve A*, negation and conditions"], ["Lexical scorer", "Keyword hits ∩ heading ranges, rare hits, overlap and section neighbors"], ["ContextVar", "Request-local sessions; hard six-call ceiling"], ["Evidence IDs", "Local spans + exact word-bounded quote validation"], ["FastAPI · Next.js", "Document API + instant-answer chat UI"], ["JSON · Postgres", "Parsed documents, answers and trace persistence"]].map(([name, text]) => <tr key={name}><th>{name}</th><td>{text}</td></tr>)}</tbody></table></div><div><div className={styles.testResult}><strong>40<span> / passed</span></strong><p>Python tests · latest local audit<br />Production build + TypeScript passed</p></div><div className={styles.measurements}><div><b>~0.26 ms</b><span>warm query tokens</span></div><div><b>~10 ms</b><span>80 sample headings</span></div><div><b>~1.1 s</b><span>cold NLTK import / process</span></div></div><p className={styles.small}>Earlier local component measurements. These are not end-to-end answering benchmarks.</p><div className={styles.eval}><h3>Next: held-out evaluation</h3><p>Correctness · abstention · evidence coverage · citation validity · budget violations · supersession · injection resistance · p50 / p95 latency</p></div></div></div><div className={styles.bottomLine}>Explicit budgets. Verifiable sources. <span>No unmeasured accuracy or competitor speedup claims.</span></div>
      </section>
    </div>
    <footer className={styles.controls}><span>{String(slide + 1).padStart(2, "0")} / 05 <small>{titles[slide]}</small></span><nav aria-label="Slides">{titles.map((title, i) => <button key={title} className={slide === i ? styles.activeDot : ""} aria-label={`Slide ${i + 1}: ${title}`} aria-current={slide === i ? "step" : undefined} onClick={() => setSlide(i)} />)}</nav><div><button disabled={slide === 0} onClick={() => setSlide(s => s - 1)} aria-label="Previous slide">←</button><button disabled={slide === 4} onClick={() => setSlide(s => s + 1)} aria-label="Next slide">→</button></div></footer>
    {showNotes && <aside className={styles.notes}><button onClick={() => setShowNotes(false)} aria-label="Close presenter notes">×</button><h2>Presenter notes / {slide + 1}</h2><p>{notes[slide]}</p><small>← → / Space: navigate · 1–5: jump · N: notes · Esc: close</small></aside>}
    {image && <div className={styles.lightbox} role="dialog" aria-modal="true" aria-label="Architecture diagram"><button autoFocus onClick={() => setImage(null)}>Close ×</button><Image src={image} alt="Supplied architecture diagram; labels from an earlier revision" width={1536} height={1024} /><p>Reference illustration — see presenter notes for current implementation differences.</p></div>}
    {notice && <p className={styles.notice} role="status" onClick={() => setNotice("")}>{notice}</p>}
  </main>;
}
