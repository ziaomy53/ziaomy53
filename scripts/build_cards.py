#!/usr/bin/env python3
"""Render the animated SVG cards for the GitHub profile README.

    python scripts/build_cards.py            -> cards/*.svg + README.md
    STATIC=1 python scripts/build_cards.py   -> cards_static/*.svg + preview.html
                                                (final frame, no animation;
                                                 README and cards/ untouched)

Everything is shown through <img>, so the SVGs use only: an inline <style>
with CSS keyframes, SMIL <animate>, and base64 WOFF fonts subset with
pyftsubset (fontTools.subset). Nothing external is referenced.
"""
from __future__ import annotations

import base64
import datetime as dt
import html
import io
import json
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = os.environ.get("STATIC", "").lower() in ("1", "true", "yes")
OUT = ROOT / ("cards_static" if STATIC else "cards")
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# --------------------------------------------------------------------------
# Theme
# --------------------------------------------------------------------------
def load_json(rel, default=None):
    p = ROOT / rel
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


DEFAULT_THEME = {
    "bg": "#0d1117", "surface": "#161b22", "border": "#30363d",
    "text": "#e6edf3", "muted": "#8b949e", "brand": "#7c5cff",
    "fonts": {
        "heading": {"family": "Space Grotesk", "file": "fonts/heading.ttf", "weight": "700"},
        "body": {"family": "Inter", "file": "fonts/body.ttf", "weight": "400"},
    },
}
_user_theme = load_json("theme.json") or {}
THEME = {**DEFAULT_THEME, **{k: v for k, v in _user_theme.items() if k != "fonts"}}
THEME["fonts"] = {**DEFAULT_THEME["fonts"], **_user_theme.get("fonts", {})}


def _rgb(h):
    h = h.lstrip("#")
    h = "".join(c * 2 for c in h) if len(h) == 3 else h
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(_rgb(a), _rgb(b)))


SURF, BORDER, TEXT, MUTED, BRAND = (THEME[k] for k in ("surface", "border", "text", "muted", "brand"))
SURF2 = mix(SURF, TEXT, 0.06)
SOFT = mix(TEXT, SURF, 0.25)
STACK = 'system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif'


# --------------------------------------------------------------------------
# Fonts: subset per card with pyftsubset, embed as base64 WOFF
# --------------------------------------------------------------------------
_warned, _faces, _metrics = set(), {}, {}


def font_file(role):
    p = ROOT / THEME["fonts"][role]["file"]
    return p if p.is_file() else None


def woff_face(role, chars):
    p = font_file(role)
    if not p:
        if role not in _warned:
            print(f"note: {THEME['fonts'][role]['file']} not found, using a system font for '{role}'", file=sys.stderr)
            _warned.add(role)
        return ""
    key = (role, chars)
    if key not in _faces:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "f.woff"
            subprocess.run(
                [sys.executable, "-m", "fontTools.subset", str(p), "--text=" + chars,
                 "--flavor=woff", "--layout-features=kern,liga", "--no-hinting",
                 "--output-file=" + str(out)],
                check=True)
            b64 = base64.b64encode(out.read_bytes()).decode()
        _faces[key] = (f'@font-face{{font-family:"c-{role}";font-weight:{THEME["fonts"][role]["weight"]};'
                       f'src:url(data:font/woff;base64,{b64}) format("woff")}}')
    return _faces[key]


def tw(s, size, role="body"):
    """Text width in px; exact when the font file is present, else an estimate."""
    if role not in _metrics:
        m, p = None, font_file(role)
        if p:
            try:
                from fontTools.ttLib import TTFont
                f = TTFont(p, lazy=True)
                m = (f.getBestCmap(), f["hmtx"], f["head"].unitsPerEm)
            except Exception:
                m = None
        _metrics[role] = m
    m = _metrics[role]
    if not m:
        return len(s) * size * 0.56
    cmap, hmtx, upm = m
    return sum(hmtx[cmap[ord(c)]][0] if ord(c) in cmap else upm * 0.5 for c in s) / upm * size


def wrap(s, size, maxw, role="body", maxlines=2):
    lines, cur = [], ""
    for w in s.split():
        t = (cur + " " + w).strip()
        if tw(t, size, role) <= maxw or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > maxlines:
        lines = lines[:maxlines]
        last = lines[-1].rstrip(".,;: ")
        while last and tw(last + "…", size, role) > maxw:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines


# --------------------------------------------------------------------------
# SVG building blocks
# --------------------------------------------------------------------------
BASE_CSS = "text{font-kerning:normal}"
ANIM_CSS = (
    "@keyframes rise{from{opacity:0;transform:translateY(12px)}}"
    "@keyframes fade{from{opacity:0}}"
    "@keyframes pop{from{opacity:0;transform:scale(.5)}}"
    "@keyframes grow{from{transform:scaleY(0)}}"
    "@keyframes draw{from{stroke-dashoffset:1}}"
    ".a{animation-duration:.75s;animation-timing-function:cubic-bezier(.2,.7,.2,1);animation-fill-mode:backwards}"
    ".rise{animation-name:rise}.fade{animation-name:fade}"
    ".pop{animation-name:pop;transform-box:fill-box;transform-origin:center}"
    ".grow{animation-name:grow;animation-duration:.9s;transform-box:fill-box;transform-origin:50% 100%}"
    ".draw{animation-name:draw;animation-duration:1s;stroke-dasharray:1}"
    ".smil-static{display:none}"
    # every CSS animation off; SMIL can't be switched off by CSS, so the animated
    # group is hidden and a static copy of it is shown instead
    "@media (prefers-reduced-motion:reduce){*{animation:none!important}"
    ".smil{display:none}.smil-static{display:inline}}"
)


def esc(s):
    return html.escape(str(s), quote=True)


def smil(animated, static):
    if STATIC:
        return f"<g>{static}</g>"
    return f'<g class="smil">{animated}</g><g class="smil-static">{static}</g>'


class Card:
    def __init__(self, name, w, h, base=0.0):
        self.name, self.w, self.h, self.base = name, w, h, base
        self.parts, self.css = [], []
        self.chars = {"heading": set(), "body": set()}

    def attrs(self, cls="", anim=None):
        classes = [cls] if cls else []
        style = ""
        if anim and not STATIC:
            kind, delay = anim
            classes += ["a", kind]
            style = f' style="animation-delay:{delay:.2f}s"'
        return (f' class="{" ".join(classes)}"' if classes else "") + style

    def add(self, s):
        self.parts.append(s)

    def frame(self, rx=20):
        self.add(f'<rect x=".5" y=".5" width="{self.w - 1}" height="{self.h - 1}" rx="{rx}" fill="{SURF}" stroke="{BORDER}"/>')

    def text(self, x, y, s, size, role="body", fill=TEXT, anchor="start", anim=None, ls=0):
        self.chars[role].update(s)
        extra = f' letter-spacing="{ls}"' if ls else ""
        a = self.attrs("h" if role == "heading" else "b", anim)
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}"{extra}{a}>{esc(s)}</text>')

    def svg(self, title):
        faces = "".join(
            woff_face(r, "".join(sorted(cs | set(" 0123456789.,")))) for r, cs in self.chars.items() if cs)
        fam = lambda r: f'"c-{r}","{THEME["fonts"][r]["family"]}",{STACK}'
        fonts = (f'.h{{font-family:{fam("heading")};font-weight:{THEME["fonts"]["heading"]["weight"]}}}'
                 f'.b{{font-family:{fam("body")};font-weight:{THEME["fonts"]["body"]["weight"]}}}')
        style = BASE_CSS + faces + fonts + ("" if STATIC else ANIM_CSS + "".join(self.css))
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" '
                f'width="{self.w}" height="{self.h}" role="img"><title>{esc(title)}</title>'
                f'<style>{style}</style>{"".join(self.parts)}</svg>')


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
def sample_data():
    print("note: data/contributions.json missing, using SAMPLE data", file=sys.stderr)
    rnd, end = random.Random(7), dt.date.today()
    days = []
    for i in range(364, -1, -1):
        d = end - dt.timedelta(days=i)
        n = 0 if rnd.random() < 0.45 else int(rnd.expovariate(0.3)) + 1
        days.append({"date": d.isoformat(), "count": n})
    return {"days": days, "repos": {}}


def analyse(days):
    ds = sorted(({"d": dt.date.fromisoformat(x["date"]), "n": int(x["count"])} for x in days), key=lambda x: x["d"])
    cur, i = 0, len(ds) - 1
    if ds[i]["n"] == 0:  # today may not have any contribution yet
        i -= 1
    while i >= 0 and ds[i]["n"] > 0:
        cur, i = cur + 1, i - 1
    longest = run = 0
    for x in ds:
        run = run + 1 if x["n"] > 0 else 0
        longest = max(longest, run)
    last = ds[-1]["d"]
    months = []
    for k in range(11, -1, -1):
        m = last.month - 1 - k
        y, m = last.year + m // 12, m % 12 + 1
        months.append((y, m, sum(x["n"] for x in ds if x["d"].year == y and x["d"].month == m)))
    busiest = max(ds, key=lambda x: x["n"])
    return {"days": ds, "total": sum(x["n"] for x in ds), "active": sum(1 for x in ds if x["n"]),
            "streak": cur, "longest": longest, "busiest": busiest, "months": months}


def fmt_date(d):
    return f"{d.day} {MON[d.month - 1]} {d.year}"


# --------------------------------------------------------------------------
# Cards
# --------------------------------------------------------------------------
def portrait_uri(path):
    if not path or not (ROOT / path).is_file():
        return None
    p = ROOT / path
    try:
        from PIL import Image
        im = Image.open(p).convert("RGB")
        s = min(im.size)
        l, t = (im.width - s) // 2, (im.height - s) // 2
        im = im.crop((l, t, l + s, t + s))
        im.thumbnail((320, 320))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
        return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


def card_hero(P, base):
    W, H = 900, 270
    c = Card("hero", W, H, base)
    c.add(f'<defs><radialGradient id="g" cx="88%" cy="0%" r="75%"><stop offset="0" stop-color="{BRAND}" stop-opacity=".3"/>'
          f'<stop offset="1" stop-color="{BRAND}" stop-opacity="0"/></radialGradient>'
          f'<clipPath id="av"><circle cx="128" cy="135" r="66"/></clipPath>'
          f'<clipPath id="fr"><rect width="{W}" height="{H}" rx="20"/></clipPath></defs>')
    c.frame()
    c.add(f'<rect width="{W}" height="{H}" rx="20" fill="url(#g)" clip-path="url(#fr)"/>')
    tx = 56
    uri = portrait_uri(P.get("portrait"))
    if uri:
        tx = 236
        c.add(f'<g{c.attrs("", ("pop", base))}><circle cx="128" cy="135" r="72" fill="none" stroke="{BRAND}" stroke-width="3"/>'
              f'<image href="{uri}" x="62" y="69" width="132" height="132" clip-path="url(#av)" preserveAspectRatio="xMidYMid slice"/></g>')
    avail = W - tx - 40
    if P.get("eyebrow"):
        c.text(tx, 66, P["eyebrow"].upper(), 13, "body", BRAND, anim=("rise", base + 0.1), ls=1.6)
    size = 52
    size = min(size, size * avail / max(tw(P["name"], size, "heading"), 1))
    c.text(tx, 126, P["name"], round(size, 1), "heading", TEXT, anim=("rise", base + 0.25))
    c.add(f'<path d="M{tx} 148h96" pathLength="1" stroke="{BRAND}" stroke-width="4" stroke-linecap="round" fill="none"'
          f'{c.attrs("", ("draw", base + 0.6))}/>')
    for i, line in enumerate(wrap(P["tagline"], 19, avail, "body", 2)):
        c.text(tx, 184 + i * 26, line, 19, "body", SOFT, anim=("rise", base + 0.75 + i * 0.12))
    if P.get("status"):
        d, y = base + 1.0, 224
        w = tw(P["status"], 13) + 52
        c.add(f'<rect x="{tx}" y="{y}" width="{w:.1f}" height="28" rx="14" fill="{mix(SURF, BRAND, .14)}" '
              f'stroke="{mix(SURF, BRAND, .5)}"{c.attrs("", ("rise", d))}/>')
        cx, cy = tx + 17, y + 14
        c.add(smil(
            f'<circle cx="{cx}" cy="{cy}" r="4" fill="{BRAND}" opacity=".5"><animate attributeName="r" values="4;11" dur="2s" begin="{d:.2f}s" repeatCount="indefinite"/>'
            f'<animate attributeName="opacity" values=".5;0" dur="2s" begin="{d:.2f}s" repeatCount="indefinite"/></circle>'
            f'<circle cx="{cx}" cy="{cy}" r="4.5" fill="{BRAND}"/>',
            f'<circle cx="{cx}" cy="{cy}" r="4.5" fill="{BRAND}"/>'))
        c.text(tx + 32, y + 19, P["status"], 13, "body", TEXT, anim=("rise", d))
    return c.svg(f"{P['name']}: {P['tagline']}")


ICONS = {
    "mail": '<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="M3.5 7l8.5 6.5L20.5 7"/>',
    "linkedin": '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M8 10.5V16M8 7.8v.1M11.5 16v-3.2a2 2 0 0 1 4 0V16M11.5 10.5V16"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z"/>',
    "file": '<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4M9.5 12h5M9.5 15.5h5"/>',
    "code": '<path d="M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16"/>',
}


def card_tile(t, i, base):
    W, H = 300, 132
    c = Card(f"tile-{i + 1}", W, H, base)
    c.frame(18)
    c.add(f'<g{c.attrs("", ("pop", base))}><rect x="22" y="22" width="44" height="44" rx="12" fill="{mix(SURF, BRAND, .16)}"/>'
          f'<g transform="translate(30.8 30.8) scale(1.1)" fill="none" stroke="{BRAND}" stroke-width="1.8" '
          f'stroke-linecap="round" stroke-linejoin="round">{ICONS.get(t.get("icon"), ICONS["globe"])}</g></g>')
    c.text(22, 98, t["label"], 20, "heading", TEXT, anim=("rise", base + 0.15))
    sub = wrap(t.get("sub", ""), 13, 256, "body", 1)
    if sub:
        c.text(22, 118, sub[0], 13, "body", MUTED, anim=("rise", base + 0.25))
    arrow = f'<path d="M0 14L14 0M4 0h10v10" fill="none" stroke="{MUTED}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
    nudge = (f'<g><animateTransform attributeName="transform" type="translate" values="0 0;3 -3;0 0" dur="2.4s" '
             f'begin="{base + 1:.2f}s" repeatCount="indefinite"/>{arrow}</g>')
    c.add(f'<g transform="translate(262 24)">{smil(nudge, arrow)}</g>')
    return c.svg(f"{t['label']}: {t.get('sub', '')}")


def card_activity(S, base):
    W, H = 900, 380
    c = Card("activity", W, H, base)
    c.frame()
    c.text(32, 46, "Contribution activity", 20, "heading", TEXT, anim=("rise", base))
    c.text(W - 32, 46, f"{S['total']:,} contributions in the last year", 13, "body", MUTED, "end", ("rise", base + 0.1))
    bw, gap = 268, 16
    cards = [
        ("CURRENT STREAK", f"{S['streak']} day{'s' if S['streak'] != 1 else ''}", f"Longest: {S['longest']} days"),
        ("ACTIVE DAYS", f"{S['active']}", f"of {len(S['days'])} days · {round(100 * S['active'] / len(S['days']))}%"),
        ("BUSIEST DAY", f"{S['busiest']['n']}", f"contributions on {fmt_date(S['busiest']['d'])}"),
    ]
    for i, (lab, val, sub) in enumerate(cards):
        x, y, d = 32 + i * (bw + gap), 68, base + 0.2 + i * 0.12
        c.add(f'<rect x="{x}" y="{y}" width="{bw}" height="88" rx="14" fill="{SURF2}"{c.attrs("", ("rise", d))}/>')
        c.text(x + 20, y + 26, lab, 11, "body", MUTED, anim=("rise", d), ls=1.4)
        c.text(x + 20, y + 58, val, 30, "heading", BRAND, anim=("rise", d + 0.05))
        c.text(x + 20, y + 77, sub, 12, "body", MUTED, anim=("rise", d + 0.1))
    x0, x1, yb, hmax = 44, 856, 336, 116
    for f in (0.33, 0.66, 1.0):
        y = yb - hmax * f
        c.add(f'<path d="M{x0} {y:.1f}H{x1}" stroke="{BORDER}" stroke-dasharray="3 5" fill="none"/>')
    c.add(f'<path d="M{x0} {yb}H{x1}" stroke="{BORDER}" fill="none"/>')
    vals = [m[2] for m in S["months"]]
    top, slot, bwid = max(max(vals), 1), (x1 - x0) / 12, 34
    for i, (y_, m_, v) in enumerate(S["months"]):
        h = max(hmax * v / top, 3)
        bx = x0 + i * slot + (slot - bwid) / 2
        d = base + 0.7 + i * 0.07
        fill = BRAND if v == max(vals) else mix(SURF, BRAND, 0.62)
        c.add(f'<rect x="{bx:.1f}" y="{yb - h:.1f}" width="{bwid}" height="{h:.1f}" rx="6" fill="{fill}"{c.attrs("bar", ("grow", d))}/>')
        c.text(bx + bwid / 2, yb - h - 8, str(v), 12, "body", TEXT, "middle", ("fade", d + 0.5))
        c.text(bx + bwid / 2, yb + 22, MON[m_ - 1], 12, "body", MUTED, "middle", ("fade", d))
    return c.svg(f"Contribution activity: {S['total']} contributions, {S['streak']}-day streak, "
                 f"{S['active']} active days, busiest day {S['busiest']['n']}")


def card_repo(f, info, base):
    W, H = 900, 168
    owner, name = f["repo"].split("/")
    c = Card(f"repo-{name}", W, H, base)
    c.frame()
    c.add(f'<g{c.attrs("", ("rise", base))} fill="none" stroke="{BRAND}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
          f'<g transform="translate(30 28) scale(1.0)"><path d="M5 4.5A2.5 2.5 0 0 1 7.5 2H19v17H7.5A2.5 2.5 0 0 0 5 21.5z"/><path d="M5 21.5V4.5M9 7h6"/></g></g>')
    c.text(62, 46, owner + " / ", 22, "heading", MUTED, anim=("rise", base))
    c.text(62 + tw(owner + " / ", 22, "heading"), 46, name, 22, "heading", TEXT, anim=("rise", base))
    chip = "FEATURED"
    cw = tw(chip, 11) + 24 + len(chip) * 1.5
    c.add(f'<rect x="{W - 32 - cw:.1f}" y="28" width="{cw:.1f}" height="26" rx="13" fill="{mix(SURF, BRAND, .14)}" '
          f'stroke="{mix(SURF, BRAND, .5)}"{c.attrs("", ("pop", base + 0.2))}/>')
    c.text(W - 32 - cw / 2 + 0.7, 45.5, chip, 11, "body", BRAND, "middle", ("pop", base + 0.2), ls=1.5)
    desc = f.get("description") or info.get("description") or ""
    for i, line in enumerate(wrap(desc, 15, W - 64, "body", 2)):
        c.text(32, 86 + i * 23, line, 15, "body", SOFT, anim=("rise", base + 0.2 + i * 0.1))
    x, y, d = 32, 142, base + 0.4
    lang = f.get("language") or (info.get("primaryLanguage") or {}).get("name")
    if lang:
        col = (info.get("primaryLanguage") or {}).get("color") or BRAND
        c.add(f'<circle cx="{x + 5}" cy="{y - 4}" r="5.5" fill="{col}"{c.attrs("", ("pop", d))}/>')
        c.text(x + 18, y, lang, 13, "body", MUTED, anim=("rise", d))
        x += 18 + tw(lang, 13) + 28
    stars = f.get("stars", info.get("stargazerCount"))
    forks = f.get("forks", info.get("forkCount"))
    star = "M12 2l3 6.5 7 .9-5.2 4.8 1.4 7L12 17.6 5.8 21.2l1.4-7L2 9.4l7-.9z"
    fork = ('<circle cx="6" cy="5" r="2.5"/><circle cx="18" cy="5" r="2.5"/><circle cx="12" cy="19" r="2.5"/>'
            '<path d="M6 7.5v2a3 3 0 0 0 3 3h6a3 3 0 0 0 3-3v-2M12 12.5v4"/>')
    for icon, val in ((star, stars), (fork, forks)):
        if val is None:
            continue
        c.add(f'<g{c.attrs("", ("rise", d))}><g transform="translate({x} {y - 13}) scale(.6)" fill="none" stroke="{MUTED}" '
              f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round">{icon}</g></g>')
        c.text(x + 20, y, str(val), 13, "body", MUTED, anim=("rise", d))
        x += 20 + tw(str(val), 13) + 26
    return c.svg(f"{f['repo']}: {desc}")


def card_graph(S, base):
    W, H = 900, 236
    c = Card("graph", W, H, base)
    c.frame()
    c.text(32, 46, "Contribution graph", 20, "heading", TEXT, anim=("rise", base))
    c.text(W - 32, 46, "Last 12 months", 13, "body", MUTED, "end", ("rise", base + 0.1))
    days = S["days"]
    off = (days[0]["d"].weekday() + 1) % 7  # weeks start on Sunday
    cols = (len(days) + off + 6) // 7
    left, avail = 64, W - 64 - 32
    pitch = min(14.0, avail / cols)
    cell = pitch - 3
    y0 = 84
    nz = sorted(x["n"] for x in days if x["n"])
    ref = max(nz[int(len(nz) * 0.9) - 1] if nz else 1, 1)
    shades = [mix(SURF, TEXT, 0.08)] + [mix(mix(SURF, TEXT, 0.08), BRAND, t) for t in (0.4, 0.62, 0.82, 1.0)]

    def lvl(n):
        if n <= 0:
            return 0
        q = n / ref
        return 1 if q <= 0.25 else 2 if q <= 0.5 else 3 if q <= 0.75 else 4

    if not STATIC:
        c.css.append("".join(f".c{k}{{animation-delay:{base + 0.3 + k * 0.016:.3f}s}}" for k in range(cols)))
    cells, last_lab = [], -9
    for idx, x in enumerate(days):
        col, row = (idx + off) // 7, (idx + off) % 7
        cx, cy = left + col * pitch, y0 + row * pitch
        cls = "" if STATIC else f' class="a pop c{col}"'
        cells.append(f'<rect{cls} x="{cx:.1f}" y="{cy:.1f}" width="{cell:.1f}" height="{cell:.1f}" rx="2.5" fill="{shades[lvl(x["n"])]}"/>')
        if x["d"].day == 1 and col - last_lab >= 3:
            c.text(cx, 72, MON[x["d"].month - 1], 11, "body", MUTED, anim=("fade", base + 0.2 + col * 0.016))
            last_lab = col
    c.add("".join(cells))
    for r in (1, 3, 5):
        c.text(left - 10, y0 + r * pitch + cell - 1, ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][r], 11, "body", MUTED, "end")
    ly = y0 + 7 * pitch + 22
    lx = W - 32 - 5 * pitch - tw("More", 11) - 8
    c.text(lx - 8, ly + cell - 1, "Less", 11, "body", MUTED, "end")
    for k in range(5):
        c.add(f'<rect x="{lx + k * pitch:.1f}" y="{ly:.1f}" width="{cell:.1f}" height="{cell:.1f}" rx="2.5" fill="{shades[k]}"/>')
    c.text(lx + 5 * pitch + 4, ly + cell - 1, "More", 11, "body", MUTED)
    return c.svg(f"Contribution graph: {S['total']} contributions in the last year")


# --------------------------------------------------------------------------
# Layout (shared by README.md and the static preview page)
# --------------------------------------------------------------------------
def layout_html(P, repos, prefix):
    out = [f'<p align="center"><img src="{prefix}hero.svg" width="100%" alt="{esc(P["name"])}: {esc(P["tagline"])}"></p>']
    tiles = "".join(f'<a href="{esc(t["url"])}"><img src="{prefix}tile-{i + 1}.svg" width="32.5%" alt="{esc(t["label"])}"></a>'
                    for i, t in enumerate(P["tiles"]))
    out.append(f'<p align="center">{tiles}</p>')
    out.append(f'<p align="center"><img src="{prefix}activity.svg" width="100%" alt="Contribution activity by month"></p>')
    for f in repos:
        n = f["repo"].split("/")[1]
        out.append(f'<p align="center"><a href="{esc(f.get("link") or "https://github.com/" + f["repo"])}"><img src="{prefix}repo-{n}.svg" width="100%" alt="{esc(f["repo"])}"></a></p>')
    out.append(f'<p align="center"><img src="{prefix}graph.svg" width="100%" alt="Contribution graph"></p>')
    return "\n".join(out) + "\n"


def main():
    P = load_json("profile.json")
    if not P:
        sys.exit("profile.json not found")
    data = load_json("data/contributions.json") or sample_data()
    S = analyse(data["days"])
    repos = P.get("featured", [])
    OUT.mkdir(exist_ok=True)

    # top-to-bottom order; every card's animations start after the one above it
    t_hero, t_tiles, t_act = 0.0, 0.9, 1.6
    t_repos = t_act + 2.4
    t_graph = t_repos + 0.5 * len(repos) + 0.3
    files = {"hero.svg": card_hero(P, t_hero)}
    for i, t in enumerate(P["tiles"][:3]):
        files[f"tile-{i + 1}.svg"] = card_tile(t, i, t_tiles + i * 0.18)
    files["activity.svg"] = card_activity(S, t_act)
    for i, f in enumerate(repos):
        info = (data.get("repos") or {}).get(f["repo"], {})
        files[f"repo-{f['repo'].split('/')[1]}.svg"] = card_repo(f, info, t_repos + i * 0.5)
    files["graph.svg"] = card_graph(S, t_graph)

    for name, svg in files.items():
        (OUT / name).write_text(svg, encoding="utf-8")
        print(f"wrote {OUT.relative_to(ROOT)}/{name}  ({len(svg) / 1024:.1f} KB)")

    if STATIC:
        page = ('<!doctype html><meta charset="utf-8"><title>Profile preview</title>'
                '<style>body{margin:0;padding:32px 0;background:#0d1117;display:flex;justify-content:center}'
                '@media (prefers-color-scheme:light){body{background:#fff}}'
                '.w{width:830px}.w p{margin:0 0 16px}.w img{vertical-align:top}</style>'
                f'<div class="w">{layout_html(P, repos, "")}</div>')
        (OUT / "preview.html").write_text(page, encoding="utf-8")
        print(f"open {OUT.relative_to(ROOT)}/preview.html and screenshot it")
    else:
        (ROOT / "README.md").write_text(
            "<!-- generated by scripts/build_cards.py; edit profile.json / theme.json instead -->\n"
            + layout_html(P, repos, "cards/"), encoding="utf-8")
        print("wrote README.md")


if __name__ == "__main__":
    main()
