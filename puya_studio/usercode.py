"""USER CODE sections: code written between
    /* USER CODE BEGIN name */  ...  /* USER CODE END name */
survives regeneration.  If a section no longer exists in the new file its code is moved to an
`#if 0` block at the end of the file instead of being deleted.
"""
import re

SECTION = re.compile(r"/\* USER CODE BEGIN ([A-Za-z0-9_ :.\-]+?) \*/\n(.*?)/\* USER CODE END \1 \*/", re.S)
ORPHAN_BEGIN = "#if 0  /* Puya Studio: user code from sections that no longer exist (move it where you need it) */"
ORPHAN_END = "#endif  /* end of orphaned user code */"
ORPHAN_BLOCK = re.compile(r"\n?" + re.escape(ORPHAN_BEGIN) + r"\n(.*?)\n" + re.escape(ORPHAN_END) + r"\n?", re.S)
ORPHAN_ITEM = re.compile(r"/\* ORPHAN \(was USER CODE ([A-Za-z0-9_ :.\-]+?)\) \*/\n(.*?)(?=/\* ORPHAN \(was USER CODE |\Z)", re.S)


def section(name, body=""):
    return f"/* USER CODE BEGIN {name} */\n{body}/* USER CODE END {name} */"


def extract(text):
    """-> ({name: body}, [(name, body) orphans already present in the file])"""
    orphans = []
    m = ORPHAN_BLOCK.search(text)
    if m:
        orphans = [(n, b.rstrip("\n") + "\n") for n, b in ORPHAN_ITEM.findall(m.group(1)) if b.strip()]
        text = text[:m.start()] + text[m.end():]
    secs = {n: b for n, b in SECTION.findall(text)}
    return secs, orphans


def fill(new_text, sections):
    """Put bodies from `sections` {name: body} into the matching sections of `new_text`."""
    def sub(m):
        name = m.group(1)
        body = sections.get(name)
        if body is None:
            return m.group(0)
        if body and not body.endswith("\n"):
            body += "\n"
        return f"/* USER CODE BEGIN {name} */\n{body}/* USER CODE END {name} */"
    return SECTION.sub(sub, new_text)


def merge(new_text, old_text):
    """Regenerated `new_text` + previous file content `old_text` -> new file text."""
    new_text = ORPHAN_BLOCK.sub("\n", new_text).rstrip("\n") + "\n"
    if not old_text:
        return new_text
    old_secs, old_orphans = extract(old_text)
    new_names = {n for n, _ in SECTION.findall(new_text)}
    merged = fill(new_text, old_secs)
    orphans = list(old_orphans)
    for name, body in old_secs.items():
        if name not in new_names and body.strip():
            orphans.append((name, body))
    # keep each orphan once
    seen, uniq = set(), []
    for n, b in orphans:
        if (n, b) not in seen:
            seen.add((n, b))
            uniq.append((n, b))
    if uniq:
        items = "".join(f"/* ORPHAN (was USER CODE {n}) */\n{b if b.endswith(chr(10)) else b + chr(10)}" for n, b in uniq)
        merged = merged.rstrip("\n") + "\n\n" + ORPHAN_BEGIN + "\n" + items.rstrip("\n") + "\n" + ORPHAN_END + "\n"
    return merged
