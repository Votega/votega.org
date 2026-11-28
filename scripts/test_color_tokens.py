#!/usr/bin/env python3
"""Guard: colors in first-party pages come from the role tokens in assets/css/tokens.css.

Fails when a tracked page, stylesheet or script:
  * writes a literal color (a hex value in a color context, or rgb()/hsl()/oklch()),
  * uses a palette token (--clay-500, ...) outside tokens.css, or
  * reads a --color-*, --chart-* or --shadow-* token that nothing defines
    (a var() with a fallback is allowed).

Named colors (white, black) are not checked. Theme and legacy files that already
carry literals are listed in BASELINE with their current count: adding one fails.

Usage:
  python scripts/test_color_tokens.py
"""

import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKENS = "assets/css/tokens.css"
EXTENSIONS = (".html", ".css", ".js", ".md")

# Not part of the themed site: local tools, docs, vendored code, brand reference
# pages, generated data, and the separate MCP worker.
SKIP_PREFIXES = ("assets/data/", "assets/img/", "assets/js/", "docs/", "mcp/", "scripts/", "tools/")
# Vendored stylesheets (social-button and code-highlight colors) and the unloaded staticman.css.
SKIP_FILES = {TOKENS, "assets/css/bootstrap-social.css", "assets/css/pygment_highlights.css",
              "assets/css/staticman.css"}

# Literal colors already present. Lower a number when you remove some; never raise it.
BASELINE = {
    "_includes/google_analytics.html": 2,       # theme's deprecation banner
    "_posts/2026-05-19-ga-primary-results.md": 2,  # inline button on a published post
    "assets/css/beautifuljekyll-minimal.css": 2,
}

HEX = r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![0-9A-Za-z_-])"
# A hex value after a color-bearing property or attribute, in the same declaration.
HEX_IN_CONTEXT = re.compile(
    r"(?:color|background|border|outline|fill|stroke|shadow|Style)[\w-]*[\"']?\s*[:=]"
    r"[^;{}<>\n]*?(?<![&\w/\"'=]" + r")(" + HEX + ")"
    r"|(?:color|background|border|outline|fill|stroke|shadow|Style)[\w-]*[\"']?\s*[:=,]\s*[\"'](" + HEX + ")")
# A complete quoted six or eight digit value, as in a JavaScript color table.
HEX_QUOTED = re.compile(r"[\"'](#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}))[\"']")
URL = re.compile(r"url\([^)]*\)")  # url(#id) is a reference, not a color
FUNCTION = re.compile(r"(?<![\w-])((?:rgba?|hsla?|hwb|oklch|oklab)\(\s*[-+.\d][^)]*\)?)")
COMMENTS = re.compile(r"/\*.*?\*/|<!--.*?-->|\{%-?\s*comment\s*-?%\}.*?\{%-?\s*endcomment\s*-?%\}", re.S)
VAR_USE = re.compile(r"var\(\s*(--[\w-]+)\s*(,|\))")
DEFINITION = re.compile(r"(--[\w-]+)\s*:")


def strip_comments(text):
    """Blank out comments, keeping line numbers."""
    return COMMENTS.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def literals(line):
    """Literal colors on one line, one entry per occurrence."""
    line = URL.sub("url()", line)
    spans = {}
    for pattern in (HEX_IN_CONTEXT, HEX_QUOTED, FUNCTION):
        for match in pattern.finditer(line):
            group = next(i for i in range(1, len(match.groups()) + 1) if match.group(i))
            spans[match.start(group)] = match.group(group)
    return [spans[k] for k in sorted(spans)]


def palette_names(tokens_css):
    """Custom properties declared in the first :root block, the palette layer."""
    block = re.search(r":root\s*\{(.*?)\}", strip_comments(tokens_css), re.S)
    return set(DEFINITION.findall(block.group(1))) if block else set()


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8", errors="replace") as handle:
        return handle.read()


def tracked_files():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True).stdout
    for path in out.decode("utf-8").split("\0"):
        if (path.endswith(EXTENSIONS) and ".min." not in path and path not in SKIP_FILES
                and not path.startswith(SKIP_PREFIXES)
                # Repository documents, not site pages.
                and path not in ("CLAUDE.md", "claude.md", "README.md", "CONTRIBUTING.md")):
            yield path


def scan(path, text, palette, defined):
    """Return (literal findings, token findings) for one file."""
    text = strip_comments(text)
    local = set(DEFINITION.findall(text))
    found_literals, found_tokens = [], []
    for number, line in enumerate(text.split("\n"), 1):
        for value in literals(line):
            found_literals.append("%s:%d: literal color %s" % (path, number, value))
        for name, after in VAR_USE.findall(line):
            if name in palette:
                found_tokens.append("%s:%d: palette token %s (use a role token)" % (path, number, name))
            elif (after == ")" and name.startswith(("--color-", "--chart-", "--shadow-"))
                  and name not in defined and name not in local):
                found_tokens.append("%s:%d: undefined token %s" % (path, number, name))
    return found_literals, found_tokens


def self_test(failures):
    """The detector must catch real colors and ignore look-alikes."""
    caught = [
        "a { color: #fff; }",
        ".x { border-left: 3px solid #b4521f }",
        "box-shadow: 0 2px 8px rgba(0,0,0,0.1);",
        "el.setAttribute('fill', '#3333ff')",
        "ctx.fillStyle = '#fff';",
        "el.setAttribute('stroke', '#000')",
        "background: linear-gradient(#fff, #000);",
        "<rect fill=\"#E81B23\"/>",
        "const COLORS = { d: '#3333ff' };",
        "background: hsl(20 50% 40%);",
        "color: var(--color-text, #222222);",
    ]
    ignored = [
        "<span class=\"icon\">&#128196;</span>",
        "<p>Senate Vote #148 passed.</p>",
        "<a href=\"#add\">Add</a>",
        "document.querySelector('#feed')",
        "background: color-mix(in srgb, var(--color-text) 18%, transparent);",
        "border-color: var(--color-border);",
        "background:url(#fade)",
    ]
    for sample in caught:
        if not literals(sample):
            failures.append("self-test: missed a color in %r" % sample)
    for sample in ignored:
        if literals(sample):
            failures.append("self-test: false finding in %r: %s" % (sample, literals(sample)))
    palette = {"--clay-500"}
    _, tokens = scan("x.css", "a{color:var(--clay-500)} b{color:var(--color-nope)}", palette, set())
    if len(tokens) != 2:
        failures.append("self-test: palette or undefined token not reported: %r" % tokens)
    _, tokens = scan("x.css", "a{color:var(--color-nope, var(--color-text))}", palette, {"--color-text"})
    if tokens:
        failures.append("self-test: fallback wrongly reported: %r" % tokens)


def main():
    failures = []
    self_test(failures)

    tokens_css = read(TOKENS)
    palette = palette_names(tokens_css)
    defined = set(DEFINITION.findall(strip_comments(tokens_css)))
    if len(palette) < 20 or "--color-text" not in defined:
        failures.append("%s: could not read the palette and role layers" % TOKENS)

    scanned = 0
    for path in tracked_files():
        scanned += 1
        found_literals, found_tokens = scan(path, read(path), palette, defined)
        failures.extend(found_tokens)
        allowed = BASELINE.get(path, 0)
        if len(found_literals) > allowed:
            failures.extend(found_literals)
            if allowed:
                failures.append("%s: %d literal colors, baseline is %d" % (path, len(found_literals), allowed))
        elif len(found_literals) < allowed:
            print("note: %s now has %d literal colors; lower its BASELINE from %d"
                  % (path, len(found_literals), allowed))
    if scanned < 50:
        failures.append("only %d files scanned; the file filter is wrong" % scanned)

    if failures:
        print("FAIL: %d color token problem(s)" % len(failures))
        for failure in failures:
            print("  " + failure)
        return 1
    print("OK: %d files use color tokens" % scanned)
    return 0


if __name__ == "__main__":
    sys.exit(main())
