#!/usr/bin/env python3
"""Format statistics log blocks into user-facing per-product report."""
from __future__ import annotations

import re
import sys
from pathlib import Path

LOG = Path(sys.argv[1] if len(sys.argv) > 1 else "qa/inbox/full_stats_report.log")
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "qa/results/FULL_POSITIONS_REPORT.md")


def _read(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    if raw[:200:2] == b"\x00" * min(100, len(raw) // 2):
        return raw.decode("utf-16-le", errors="replace")
    return raw.decode("utf-8", errors="replace")


def main():
    if not LOG.exists():
        print("missing log", LOG)
        return 1
    text = _read(LOG)
    parts = re.split(r"Generated statistics block for '([^']+)':\r?\n", text)
    products = []
    i = 1
    while i < len(parts) - 1:
        name = parts[i]
        body = parts[i + 1]
        m = re.search(r"\r?\n\d{4}-\d{2}-\d{2} ", body)
        if m:
            body = body[: m.start()]
        products.append((name, body.strip()))
        i += 2

    lines = [
        "# Полный отчёт по каждой позиции",
        "",
        f"Источник: `{LOG.as_posix()}`",
        f"Продуктов: **{len(products)}**",
        "",
        "Формат = как в stats Telegram (4 корзины + лимит + ссылки).",
        "",
    ]
    for idx, (name, body) in enumerate(products, 1):
        # Clean HTML-ish for markdown readability but keep structure
        clean = body
        clean = re.sub(r"<b>(.*?)</b>", r"**\1**", clean)
        clean = re.sub(r"<code>(.*?)</code>", r"`\1`", clean)
        clean = re.sub(
            r'<a href="([^"]+)"><b>\*ТЫК\*</b></a>',
            r"[*ТЫК*](\1)",
            clean,
        )
        clean = re.sub(r"<[^>]+>", "", clean)
        clean = clean.replace("&amp;", "&")
        # normalize spaces on bucket lines
        lines.append(f"## {idx}. {name}")
        lines.append("")
        lines.append("```")
        lines.append(clean)
        lines.append("```")
        lines.append("")

    # empty summary
    empty_all = []
    for name, body in products:
        prices = re.findall(r"(?:Sofort\+|Auktion\+|Sofort|Auktion)\s+([0-9.]+|---)", body)
        # crude: if all ---
        if prices and all(p == "---" for p in prices[:4]):
            empty_all.append(name)
        elif body.count("---") >= 4 and "€" not in body.replace("2500€", "").replace("50€", ""):
            # check no price numbers in buckets
            if not re.search(r"(?:Sofort\+|Auktion\+|Sofort|Auktion)\s+[0-9]", body):
                empty_all.append(name)

    lines += ["---", "", f"### Все 4 корзины empty: {len(empty_all)}", ""]
    for n in empty_all:
        lines.append(f"- {n}")
    lines.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"products={len(products)} empty_all={len(empty_all)} -> {OUT}")
    # also print to stdout for chat
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
