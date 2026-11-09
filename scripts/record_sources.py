"""Write/refresh the `source:` block of each film in films.yaml WITHOUT disturbing comments or other fields.

Usage: record_sources.py films.yaml sources.tsv      (tsv: id <TAB> url <TAB> page <TAB> license <TAB> size_bytes <TAB> date)
"""
import sys
from pathlib import Path


def record(text, rows):
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        if line.startswith("  - id: "):
            fid = line.split(":", 1)[1].strip()
            block = []
            while i < len(lines) and not lines[i].startswith("  - id: "):
                block.append(lines[i])
                i += 1
            # drop any previous source: block (the key line plus its deeper-indented children)
            cleaned, skipping = [], False
            for b in block:
                if b.startswith("    source:"):
                    skipping = True
                    continue
                if skipping and (b.startswith("      ") or b.strip() == ""):
                    continue
                skipping = False
                cleaned.append(b)
            while cleaned and cleaned[-1].strip() == "":
                cleaned.pop()
            out.extend(cleaned)
            if fid in rows:
                r = rows[fid]
                out += ["    source:", f"      url: {r['url']}", f"      page: {r['page']}",
                        f"      license_at_source: {r['license']}", f"      size_bytes: {r['size']}",
                        f"      verified: {r['date']}"]
    return "\n".join(out) + "\n"


def parse_tsv(path):
    rows = {}
    for ln in Path(path).read_text().splitlines():
        if not ln.strip():
            continue
        fid, url, page, lic, size, date = ln.split("\t")
        rows[fid] = {"url": url, "page": page, "license": lic, "size": size, "date": date}
    return rows


if __name__ == "__main__":
    films_path, tsv = Path(sys.argv[1]), sys.argv[2]
    films_path.write_text(record(films_path.read_text(), parse_tsv(tsv)))
