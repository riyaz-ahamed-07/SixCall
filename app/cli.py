from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def _configure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _hr(char: str = "─", width: int = 64) -> str:
    return char * width


def _print_ask_pretty(answer: Any, question: str) -> None:
    ok = answer.status == "ok"
    badge = "OK" if ok else "INSUFFICIENT INFORMATION"
    pages = ", ".join(str(p) for p in answer.pages_used) or "—"

    print()
    print(_hr("═"))
    print("  SixCall — test view")
    print(_hr("═"))
    print(f"  Q: {question}")
    print(f"  Status: {badge}")
    print(f"  Intent: {getattr(answer, 'intent', None) or '—'}")
    print(f"  Strat:  {getattr(answer, 'strategy', None) or '—'}")
    print(f"  Pages:  {pages}")
    print(f"  Calls:  {answer.calls_used}/6")
    print(f"  QID:    {answer.question_id}")
    print(_hr())
    print()
    print("  ANSWER")
    print(_hr("·"))
    for line in (answer.text or "").splitlines() or ["(empty)"]:
        print(f"  {line}")
    print()

    if answer.quotes:
        print("  QUOTES")
        print(_hr("·"))
        for i, q in enumerate(answer.quotes, 1):
            page = q.get("page", "?")
            text = str(q.get("text") or "").strip()
            print(f"  [{i}] p.{page}")
            print(f"      \"{text}\"")
            print()
    else:
        print("  QUOTES: (none)")
        print()

    if answer.reason and not ok:
        print("  REASON")
        print(_hr("·"))
        print(f"  {answer.reason}")
        print()

    if answer.tool_trace:
        print("  TOOL TRACE")
        print(_hr("·"))
        for step in answer.tool_trace:
            idx = step.get("call_index", "?")
            tool = step.get("tool", "?")
            args = step.get("args") or {}
            summary = step.get("result_summary", "")
            err = step.get("error")
            arg_bits = []
            if "keyword" in args:
                arg_bits.append(f"kw={args['keyword']!r}")
            if "page_number" in args:
                arg_bits.append(f"page={args['page_number']}")
            if "doc_id" in args and tool == "list_headings":
                arg_bits.append("doc")
            arg_s = (", ".join(arg_bits) if arg_bits else "")
            mark = "x" if err else "ok"
            print(f"  {idx}. [{mark}] {tool} {arg_s}".rstrip())
            print(f"      → {summary}")
        print()

    print(_hr("═"))
    print("  tip: add --json for raw payload · python -m app.cli trace <qid>")
    print(_hr("═"))
    print()


def _print_trace_pretty(trace: list[dict[str, Any]], question_id: str) -> None:
    print()
    print(_hr("═"))
    print(f"  Trace · {question_id}")
    print(_hr("═"))
    if not trace:
        print("  (empty — unknown question_id or process-only memory miss)")
        print(_hr("═"))
        print()
        return
    for step in trace:
        idx = step.get("call_index", "?")
        tool = step.get("tool", "?")
        args = step.get("args") or {}
        summary = step.get("result_summary", "")
        err = step.get("error")
        print(f"  {idx}. {tool}  args={json.dumps(args, ensure_ascii=False)}")
        print(f"      {summary}")
        if err:
            print(f"      error: {err}")
        print()
    print(_hr("═"))
    print()


def main(argv: list[str] | None = None) -> int:
    _configure_stdout()
    from app.api import ask, get_trace, ingest_pdf, list_docs, overview

    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Budgeted document-answering agent (CLI)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ingest = sub.add_parser("ingest", help="Ingest a PDF and print doc_id")
    p_ingest.add_argument("path", help="Path to PDF")

    p_ask = sub.add_parser("ask", help="Ask a question about an ingested doc")
    p_ask.add_argument("doc_id")
    p_ask.add_argument("question")
    p_ask.add_argument(
        "--json",
        action="store_true",
        help="Print raw JSON (default is pretty test view)",
    )

    p_overview = sub.add_parser(
        "overview", help="Document overview (headings + ≤5 pages)"
    )
    p_overview.add_argument("doc_id")
    p_overview.add_argument(
        "question",
        nargs="?",
        default="What is this document about?",
        help="Optional overview prompt",
    )
    p_overview.add_argument("--json", action="store_true")

    p_trace = sub.add_parser("trace", help="Print tool trace for a question_id")
    p_trace.add_argument("question_id")
    p_trace.add_argument("--json", action="store_true", help="Print raw JSON")

    p_docs = sub.add_parser("docs", help="List ingested documents")
    p_docs.add_argument("--json", action="store_true", help="Print raw JSON")

    sub.add_parser(
        "migrate",
        help="Create/upgrade Postgres tables (DATABASE_URL → Supabase *dev* only)",
    )

    args = parser.parse_args(argv)

    if args.cmd == "migrate":
        from app.db import migrate

        migrate()
        print("migrate ok")
        return 0

    if args.cmd == "ingest":
        doc_id = ingest_pdf(args.path)
        print()
        print(_hr("═"))
        print("  Ingested")
        print(_hr("·"))
        print(f"  doc_id: {doc_id}")
        print(_hr("═"))
        print()
        return 0

    if args.cmd == "ask":
        answer = ask(args.doc_id, args.question)
        if args.json:
            print(json.dumps(answer.model_dump(), indent=2, ensure_ascii=False))
        else:
            _print_ask_pretty(answer, args.question)
        return 0 if answer.status == "ok" else 2

    if args.cmd == "overview":
        answer = overview(args.doc_id, args.question)
        if args.json:
            print(json.dumps(answer.model_dump(), indent=2, ensure_ascii=False))
        else:
            _print_ask_pretty(answer, args.question)
        return 0 if answer.status == "ok" else 2

    if args.cmd == "trace":
        trace = get_trace(args.question_id)
        if args.json:
            print(json.dumps(trace, indent=2, ensure_ascii=False))
        else:
            _print_trace_pretty(trace, args.question_id)
        return 0

    if args.cmd == "docs":
        docs = list_docs()
        if args.json:
            print(json.dumps(docs, indent=2, ensure_ascii=False))
        else:
            print()
            print(_hr("═"))
            print("  Documents")
            print(_hr("═"))
            if not docs:
                print("  (none ingested yet)")
            for d in docs:
                print(f"  • {d.get('title')}")
                print(f"      id={d.get('doc_id')}  pages={d.get('page_count')}")
            print(_hr("═"))
            print()
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
