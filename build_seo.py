#!/usr/bin/env python3
"""
Generate SEO pages for seedoilfree.io from the listings in index.html.

  python3 build_seo.py

Outputs (all static, safe to re-run):
  nyc/<borough>/index.html          borough hubs
  nyc/<neighborhood>/index.html     neighborhoods with 2+ listings
  restaurants/<id>/index.html       one page per NYC independent
  chains/index.html, chains/<id>/   chain ordering guides
  sitemap.xml                       every page above + homepage
and injects a "Browse" link block into index.html (between markers).

Source of truth is still index.html; edit listings there, then re-run.
Only facts already in index.html are used. Nothing is invented.
"""
import html as H
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
SITE = "https://www.seedoilfree.io"
TODAY = "2026-11-16"
FORM = "https://docs.google.com/forms/d/e/1FAIpQLScsp772u4Dn8vuZAyEnDB0y6Jvti7MJqHUeB5YC0RHwp_Le4Q/viewform?usp=sharing"
BOROUGHS = {"manhattan": "Manhattan", "brooklyn": "Brooklyn", "queens": "Queens"}

src = (ROOT / "index.html").read_text(encoding="utf-8")
CSS = re.search(r"<style>(.*?)</style>", src, re.S).group(1)
GTAG = re.search(r"<!-- Google tag.*?</script>\s*<script>.*?</script>", src, re.S).group(0)
FONTS = re.search(r'<link href="https://fonts.googleapis.com[^>]+>', src).group(0)


def slugify(t):
    t = H.unescape(t).lower().replace("&", " and ")
    t = re.sub(r"['’`]", "", t)
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def strip_tags(t):
    return H.unescape(re.sub(r"<[^>]+>", "", t)).strip()


# ---------- parse listings ----------
rows = []
pat = re.compile(
    r'<div class="row" id="([^"]+)" data-state="(\w+)" data-status="(\w+)" '
    r'data-type="(\w+)" data-area="(\w+)">(.*?)\n    </div>\n', re.S)
for m in pat.finditer(src):
    rid, state, status, typ, area, body = m.groups()
    g = lambda cls: (re.search(r'class="%s"[^>]*>(.*?)</(?:div|h3|a)>' % cls, body, re.S) or [None, ""])[1]
    name = strip_tags(re.sub(r'<span class="new-badge">.*?</span>', "", g("row-name")))
    loc_raw = g("row-loc")
    loc = strip_tags(loc_raw)
    ig = re.search(r'class="ig-link" href="([^"]+)"[^>]*>.*?(@[\w.]+)', body, re.S)
    icon = strip_tags(g("row-icon"))
    hood = loc.split(",")[0].strip() if state == "NY" and typ == "independent" else None
    rows.append(dict(
        id=rid, state=state, status=status, type=typ, area=area, name=name, loc=loc,
        verified="verified in person" in loc_raw, note=strip_tags(g("row-note")),
        fat=strip_tags(g("row-fat")), ig_url=ig.group(1) if ig else None,
        ig_handle=ig.group(2) if ig else None, icon=icon, hood=hood))

nyc = [r for r in rows if r["state"] == "NY" and r["type"] == "independent"]
chains = [r for r in rows if r["type"] == "chain"]
by_hood = defaultdict(list)
by_borough = defaultdict(list)
for r in nyc:
    by_hood[r["hood"]].append(r)
    by_borough[r["area"]].append(r)
hood_pages = {h: v for h, v in by_hood.items() if len(v) >= 2}
# hood -> borough (first listing wins)
hood_borough = {h: v[0]["area"] for h, v in by_hood.items()}
PILL = {"clean": "CLEAN", "partial": "PARTIAL", "hack": "HACK ONLY"}
STATUS_TXT = {
    "clean": "cooks without seed oils",
    "partial": "is only partly seed-oil-free (some items or the fryer still use seed oil)",
    "hack": "uses seed oils, but you can order around them",
}


def e(t):
    return H.escape(t, quote=True)


def url_for(kind, key):
    return f"/{kind}/{key}/"


def card(r, link=True):
    href = url_for("chains", r["id"]) if r["type"] == "chain" else url_for("restaurants", r["id"])
    name = f'<a href="{href}">{e(r["name"])}</a>' if link else e(r["name"])
    ig = f'<a class="ig-link" href="{e(r["ig_url"])}" target="_blank" rel="noopener">📷 {e(r["ig_handle"])}</a>' if r["ig_url"] else ""
    ver = ' · <span class="verified-tag">✓ verified in person</span>' if r["verified"] else ""
    loc = e(r["loc"].replace("✓ verified in person", "").rstrip(" ·"))
    # a "clean" listing nobody has verified in person is shown as REPORTED, not CLEAN
    reported = r["status"] == "clean" and not r["verified"] and r["type"] == "independent"
    pill_cls, pill_txt = ("reported", "REPORTED") if reported else (r["status"], PILL[r["status"]])
    return f'''<div class="row">
  <div class="row-icon">{r["icon"]}</div>
  <div class="row-main">
    <h3 class="row-name">{name}</h3>
    <div class="row-loc">{loc}{ver}</div>
    <div class="row-note">{e(r["note"])}</div>
    <div class="row-fat">{e(r["fat"])}</div>
    {ig}
  </div>
  <div class="pill {pill_cls}">{pill_txt}</div>
</div>'''


def crumbs(items):
    return {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": n, "item": SITE + p}
        for i, (n, p) in enumerate(items)]}


def faq_ld(qas):
    return {"@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in qas]}


def page(path, title, desc, h1, intro, body, ld, crumb_items, extra_faq=None, extra_html=""):
    canon = SITE + path
    graph = [crumbs(crumb_items)] + ld
    if extra_faq:
        graph.append(faq_ld(extra_faq))
    extra_block = f"\n  {extra_html}" if extra_html else ""
    faq_html = ""
    if extra_faq:
        faq_html = '<section class="info-section"><h2>Common questions</h2>' + "".join(
            f"<h3>{e(q)}</h3><p>{e(a)}</p>" for q, a in extra_faq) + "</section>"
    crumb_html = " › ".join(
        f'<a href="{p}">{e(n)}</a>' if i < len(crumb_items) - 1 else e(n) for i, (n, p) in enumerate(crumb_items))
    doc = f'''<!DOCTYPE html>
<html lang="en">
<head>
{GTAG}
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{canon}">
<meta name="robots" content="index, follow, max-image-preview:large">
<meta name="theme-color" content="#4F7A5A">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/favicon-192.png" sizes="192x192" type="image/png">
<meta property="og:site_name" content="SeedOilFree">
<meta property="og:type" content="website">
<meta property="og:url" content="{canon}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:image" content="{SITE}/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False)}</script>
{FONTS}
<style>{CSS}
  .crumbs {{ font-size: 13px; color: var(--ink-soft); margin: 0 0 14px; }}
  .crumbs a, .row-name a {{ color: inherit; }}
  .pill.reported {{ background: var(--amber-soft); color: var(--amber); }}
  .navlinks a {{ display: inline-block; margin: 0 10px 8px 0; }}
</style>
</head>
<body>
<div class="page">
  <header>
    <div class="brand"><a href="/" style="text-decoration:none;color:inherit"><p class="wordmark">Seedoilfree</p></a></div>
    <div class="header-right"><a class="top-submit-link" href="{FORM}" target="_blank">Restaurant Submission Form</a></div>
  </header>
  <main>
  <p class="crumbs">{crumb_html}</p>
  <h1 class="page-title">{e(h1)}</h1>
  <p class="sub">{intro}</p>
  <div class="rows">
{body}
  </div>{extra_block}
  {faq_html}
  <section class="submit-box">
    <div class="title">Know a spot that's missing?</div>
    <p>Tell us the name, neighborhood, and what oil they cook with. We label every listing so you know whether we have verified it in person.</p>
    <a href="{FORM}" target="_blank">Verify or suggest a spot →</a>
  </section>
  <p><a href="/">← All seed oil free restaurants in NYC</a></p>
  </main>
</div>
</body>
</html>
'''
    out = ROOT / path.strip("/") / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")


def rest_ld(r):
    d = {"@type": "Restaurant", "name": r["name"], "url": SITE + url_for("restaurants", r["id"]),
         "description": r["note"], "address": {"@type": "PostalAddress", "addressLocality": r["hood"] or "New York",
                                              "addressRegion": "NY", "addressCountry": "US"}}
    if r["ig_url"]:
        d["sameAs"] = [r["ig_url"]]
    return d



# ---------- hub enrichment helpers (facts come only from the parsed listings) ----------
FAT_WORDS = [("tallow", "beef tallow"), ("butter", "butter"), ("ghee", "ghee"), ("olive", "olive oil"), ("evoo", "olive oil"),
             ("lard", "pork lard"), ("avocado", "avocado oil"), ("coconut", "coconut oil")]


def plural(n, one, many=None):
    return f"{n} {one if n == 1 else (many or one + 's')}"


def glance_html(items, where):
    n = len(items)
    ver = sum(r["verified"] for r in items)
    clean = [r for r in items if r["status"] == "clean"]
    partial = [r for r in items if r["status"] == "partial"]
    hack = [r for r in items if r["status"] == "hack"]
    reported = [r for r in clean if not r["verified"]]
    unver = n - ver
    if ver == 0:
        parts = [f"{plural(n, 'listing')} in {e(where)}, none verified in person by us yet."]
    else:
        parts = [f"Of the {plural(n, 'listing')} in {e(where)}, {ver} {'was' if ver == 1 else 'were'} verified in person by us."]
    bits = []
    if clean:
        bits.append(f"{len(clean)} {'is' if len(clean) == 1 else 'are'} listed as cooking without seed oils")
    if partial:
        bits.append(f"{len(partial)} {'is' if len(partial) == 1 else 'are'} only partly seed-oil-free")
    if hack:
        bits.append(f"{len(hack)} use{'s' if len(hack) == 1 else ''} seed oil but can be ordered around")
    if bits:
        parts.append("; ".join(bits).capitalize() + ".")
    if unver and ver:
        parts.append(f"{unver} other{'' if unver == 1 else 's'} {'is' if unver == 1 else 'are'} not yet verified in person and {'comes' if unver == 1 else 'come'} from public sources.")
    elif unver:
        parts.append("These listings come from public sources and are not yet verified in person.")
    found = []
    for label in dict.fromkeys(l for _, l in FAT_WORDS):
        keys = [k for k, l in FAT_WORDS if l == label]
        c = sum(1 for r in items if any(k in r["fat"].lower() for k in keys))
        if c:
            found.append((c, label))
    found.sort(key=lambda t: (-t[0], t[1]))
    if found:
        parts.append("Cooking fats named across these listings: " + ", ".join(f"{e(l)} ({plural(c, 'spot')})" for c, l in found) + ".")
    return ('<section class="info-section"><h2>At a glance</h2><p>' + " ".join(parts) + "</p></section>")


def labels_html():
    return ('<section class="info-section"><h2>What the labels mean</h2>'
            "<p><strong>CLEAN</strong>: cooks without seed oils. "
            "<strong>PARTIAL</strong>: some items or the fryer still use seed oil. "
            "<strong>HACK ONLY</strong>: uses seed oils, but you can order around them. "
            "<strong>REPORTED</strong>: listed as seed-oil-free by public sources, not yet verified in person. "
            "Kitchens change suppliers, so confirm with the restaurant before you go. <a href=\"/how-we-verify/\">How we verify</a></p></section>")


def nearby_html(h, b):
    sib = [(x, v) for x, v in sorted(hood_pages.items()) if x != h and hood_borough[x] == b]
    out = []
    if sib:
        out.append('<p class="navlinks">' + "".join(
            f'<a href="/nyc/{slugify(x)}/">{e(x)} ({len(v)})</a>' for x, v in sib) + "</p>")
    others = [r for r in by_borough[b] if r["hood"] != h and r["verified"]][:6]
    if others:
        out.append("<p>Other verified spots in " + e(BOROUGHS[b]) + ": " + ", ".join(
            f'<a href="{url_for("restaurants", r["id"])}">{e(r["name"])}</a> ({e(r["hood"])})' for r in others) + ".</p>")
    out.append(f'<p><a href="/nyc/{b}/">All {e(BOROUGHS[b])} listings</a> · <a href="/chains/">Chain ordering guides</a></p>')
    return '<section class="info-section"><h2>Keep exploring</h2>' + "".join(out) + "</section>"


urls = [("/", "1.0")]
n_hood = n_rest = n_chain = 0

# ---------- borough hubs ----------
for b, label in BOROUGHS.items():
    items = by_borough.get(b, [])
    if not items:
        continue
    ver = sum(r["verified"] for r in items)
    hoods = sorted({r["hood"] for r in items})
    links = "".join(
        f'<a href="/nyc/{slugify(h)}/">{e(h)}</a>' if h in hood_pages else f"<span>{e(h)}</span> " for h in hoods)
    path = f"/nyc/{b}/"
    page(path,
         f"Seed Oil Free Restaurants in {label}, NYC ({len(items)} listings) | SeedOilFree",
         f"{len(items)} {label} restaurants that cook without seed oils, {ver} verified in person. Tallow, butter, olive oil and more, by neighborhood.",
         f"Seed Oil Free Restaurants in {label}",
         f"{len(items)} {label} restaurants listed as cooking without seed oils; {ver} confirmed in person. Neighborhoods: " + ", ".join(e(h) for h in hoods) + ".",
         "\n".join(card(r) for r in sorted(items, key=lambda r: (not r["verified"], r["name"]))),
         [{"@type": "ItemList", "name": f"Seed oil free restaurants in {label}",
           "itemListElement": [{"@type": "ListItem", "position": i + 1, "item": rest_ld(r)} for i, r in enumerate(items)]}],
         [("Home", "/"), (label, path)],
         [(f"Are there seed oil free restaurants in {label}?",
           f"Yes. SeedOilFree lists {len(items)} in {label}, and {ver} of them have been verified in person. The rest are reported as seed-oil-free but not yet confirmed.")],
         extra_html=glance_html(items, label) + labels_html() + '<section class="info-section"><h2>Neighborhoods</h2><p class="navlinks">' + links + '</p></section>')
    urls.append((path, "0.8"))

# ---------- neighborhood pages ----------
for h, items in sorted(hood_pages.items()):
    ver = sum(r["verified"] for r in items)
    names = ", ".join(r["name"] for r in items[:3])
    b = hood_borough[h]
    path = f"/nyc/{slugify(h)}/"
    page(path,
         f"Seed Oil Free Restaurants in {h}, NYC | SeedOilFree",
         f"{len(items)} seed oil free restaurants in {h}: {names}. {ver} verified in person. Updated {TODAY}.",
         f"Seed Oil Free Restaurants in {h}",
         f"{len(items)} {h} restaurants listed as cooking without seed oils; {ver} confirmed in person. Last updated {TODAY}.",
         "\n".join(card(r) for r in sorted(items, key=lambda r: (not r["verified"], r["name"]))),
         [{"@type": "ItemList", "name": f"Seed oil free restaurants in {h}",
           "itemListElement": [{"@type": "ListItem", "position": i + 1, "item": rest_ld(r)} for i, r in enumerate(items)]}],
         [("Home", "/"), (BOROUGHS[b], f"/nyc/{b}/"), (h, path)],
         [(f"What are the best seed oil free restaurants in {h}?",
           f"SeedOilFree lists {len(items)} in {h}: " + ", ".join(r["name"] for r in items) + f". {ver} have been verified in person.")],
         extra_html=glance_html(items, h) + labels_html() + nearby_html(h, b))
    urls.append((path, "0.8"))
    n_hood += 1

# ---------- restaurant pages ----------
for r in nyc:
    b = r["area"]
    path = url_for("restaurants", r["id"])
    status_line = "Verified in person by SeedOilFree." if r["verified"] else "Reported as seed-oil-free but not yet verified in person."
    near = [x for x in by_hood[r["hood"]] if x["id"] != r["id"]][:4]
    near_html = ""
    if near:
        near_html = f'<section class="info-section"><h2>More in {e(r["hood"])}</h2>' + "".join(
            f'<p><a href="{url_for("restaurants", x["id"])}">{e(x["name"])}</a>: {e(x["fat"])}</p>' for x in near) + "</section>"
    body = card(r, link=False) + near_html
    page(path,
         f"Is {r['name']} Seed Oil Free? ({r['hood']}, NYC) | SeedOilFree",
         f"{r['name']} in {r['hood']}, NYC: {r['fat']}. {status_line}",
         f"Is {r['name']} Seed Oil Free?",
         f"{e(r['name'])} in {e(r['hood'])} " + ("is reported to cook without seed oils" if r["status"] == "clean" and not r["verified"] else STATUS_TXT[r["status"]]) + f". {status_line} Last checked {TODAY}.",
         body,
         [rest_ld(r)],
         [("Home", "/"), (BOROUGHS.get(b, "NYC"), f"/nyc/{b}/"), (r["name"], path)],
         [(f"What oil does {r['name']} cook with?", f"{r['fat']}. {status_line}"),
          (f"Is {r['name']} seed oil free?", f"{r['note']}")])
    urls.append((path, "0.6"))
    n_rest += 1

# ---------- chain pages ----------
for r in chains:
    path = url_for("chains", r["id"])
    page(path,
         f"Is {r['name']} Seed Oil Free? What to Order | SeedOilFree",
         f"{r['name']} cooking oils and how to order around seed oils. {r['fat']}.",
         f"Is {r['name']} Seed Oil Free?",
         f"{e(r['name'])} {STATUS_TXT[r['status']]}. Ingredients and practices change by location, so confirm with your store.",
         card(r, link=False) + '<p><a href="/chains/">All chain restaurant guides →</a></p>',
         [{"@type": "Article", "headline": f"Is {r['name']} seed oil free?", "dateModified": TODAY,
           "author": {"@type": "Organization", "name": "SeedOilFree"}, "mainEntityOfPage": SITE + path}],
         [("Home", "/"), ("Chains", "/chains/"), (r["name"], path)],
         [(f"What oil does {r['name']} use?", r["fat"] + "."),
          (f"How do I order seed oil free at {r['name']}?", r["note"])])
    urls.append((path, "0.7"))
    n_chain += 1

page("/chains/",
     "Which Chain Restaurants Are Seed Oil Free? Ordering Guides | SeedOilFree",
     f"Cooking oils and ordering tips for {len(chains)} national chains, from tallow fryers to order-around hacks.",
     "Seed Oil Free Chain Restaurant Guides",
     f"{len(chains)} national chains: which cook without seed oils, which are partial, and how to order around them.",
     "\n".join(card(r) for r in sorted(chains, key=lambda r: (r["status"] != "clean", r["status"], r["name"]))),
     [], [("Home", "/"), ("Chains", "/chains/")],
     [("Which chain restaurants cook without seed oils?",
       "See the guides above. Statuses are Clean, Partial, or Hack only, and practices can vary by location.")])
urls.append(("/chains/", "0.8"))


# ---------- how we verify (facts: existing site copy + live counts) ----------
n_ver = sum(r["verified"] for r in nyc)
vp = "/how-we-verify/"
verify_body = f"""<section class="info-section"><h2>What the labels mean</h2>
<p><strong>Verified in person.</strong> SeedOilFree confirmed the listing in person. These carry a verified tag. Right now that is {n_ver} of {len(nyc)} NYC independent listings.</p>
<p><strong>CLEAN</strong> means the restaurant cooks without seed oils. <strong>PARTIAL</strong> means some items or the fryer still use seed oil. <strong>HACK ONLY</strong> means it uses seed oils, but you can order around them.</p>
<p><strong>REPORTED</strong> means the restaurant is listed as seed-oil-free by other sources but we have not confirmed it yet.</p></section>
<section class="info-section"><h2>Where unverified listings come from</h2>
<p>Reported listings come from other seed oil free directories, community posts, and press coverage. We show them because they can help you, and we label them so you know they are unconfirmed. Chain listings come from public databases and community reports, and they can change.</p></section>
<section class="info-section"><h2>Corrections and new listings</h2>
<p>Readers help keep the directory accurate. If a listing is wrong, or you know a spot we are missing, send it through the <a href="{FORM}" target="_blank" rel="noopener">restaurant submission form</a> with the restaurant name, neighborhood, and what oil it cooks with.</p></section>
<section class="info-section"><h2>Limits</h2>
<p>Kitchens change suppliers and fryer oils without notice, and a verified tag shows what we confirmed at the time. Confirm with the restaurant before you go, especially if you are avoiding seed oils for a medical reason.</p>
<p><a href="/nyc/manhattan/">Manhattan</a> · <a href="/nyc/brooklyn/">Brooklyn</a> · <a href="/nyc/queens/">Queens</a> · <a href="/chains/">Chain guides</a></p></section>"""
page(vp,
     "How SeedOilFree Verifies Restaurants | SeedOilFree",
     f"How SeedOilFree labels NYC restaurants: {n_ver} of {len(nyc)} independent listings verified in person, plus what REPORTED, CLEAN, PARTIAL and HACK ONLY mean.",
     "How SeedOilFree Verifies Restaurants",
     "Every listing shows how much we know about it. Here is what each label means and where the unverified ones come from.",
     "", [{"@type": "AboutPage", "name": "How SeedOilFree verifies restaurants", "url": SITE + vp}],
     [("Home", "/"), ("How we verify", vp)], extra_html=verify_body)
urls.append((vp, "0.5"))

# ---------- sitemap ----------
sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
for p, pr in urls:
    sm.append(f"  <url><loc>{SITE}{p}</loc><lastmod>{TODAY}</lastmod><priority>{pr}</priority></url>")
sm.append("</urlset>\n")
(ROOT / "sitemap.xml").write_text("\n".join(sm), encoding="utf-8")

# ---------- homepage internal links (idempotent) ----------
A, B = "<!-- seo-browse:start -->", "<!-- seo-browse:end -->"
blk = [A, '<section class="info-section" id="browse"><h2>Browse seed oil free restaurants</h2><p class="navlinks">']
for b, label in BOROUGHS.items():
    if by_borough.get(b):
        blk.append(f'<a href="/nyc/{b}/">{label}</a>')
blk.append("</p><p class=\"navlinks\">")
for h in sorted(hood_pages):
    blk.append(f'<a href="/nyc/{slugify(h)}/">{e(h)}</a>')
blk.append('</p><p class="navlinks"><a href="/chains/">Chain restaurant guides</a> <a href="/how-we-verify/">How we verify</a></p></section>')
blk.append(B)
block = "\n".join(blk)
if A in src:
    src = re.sub(re.escape(A) + ".*?" + re.escape(B), block.replace("\\", "\\\\"), src, flags=re.S)
else:
    src = src.replace('<section class="submit-box">', block + '\n\n  <section class="submit-box">', 1)
# unverified "clean" independents show REPORTED on the homepage too
def _fix_home_pill(m):
    blk = m.group(0)
    if "reported, unverified" in blk:
        blk = blk.replace('<div class="pill clean">CLEAN</div>', '<div class="pill reported">REPORTED</div>')
    return blk
src = pat.sub(_fix_home_pill, src)
if ".pill.reported" not in src:
    src = src.replace("  .pill.hack {", "  .pill.reported { background: var(--amber-soft); color: var(--amber); }\n  .pill.hack {", 1)
(ROOT / "index.html").write_text(src, encoding="utf-8")

print(f"{len(rows)} listings -> {len(urls)} URLs "
      f"({n_hood} neighborhoods, {len(by_borough)} boroughs, {n_rest} restaurants, {n_chain} chains)")
