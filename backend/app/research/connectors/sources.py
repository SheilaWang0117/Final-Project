"""Public-source connectors (no paid keys required).

Each `search_*` function takes a guard-checked public query, returns
normalized items, and raises on failure so callers can record coverage gaps.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from urllib.parse import quote, urlencode, urljoin

import feedparser
from bs4 import BeautifulSoup

from ...config import get_settings
from ..cache import CacheStats, cached_fetch
from .base import clean_text, item, iso_date, matches

# ----------------------------------------------------------- ClinicalTrials.gov


async def search_clinicaltrials(query: str, *, stats: CacheStats, limit: int = 10, since: date | None = None) -> list[dict]:
    """ClinicalTrials.gov API v2 (human studies; useful for comparative-oncology targets)."""
    params = {"query.term": query, "pageSize": str(min(limit, 20)), "sort": "LastUpdatePostDate:desc",
              "fields": "NCTId,BriefTitle,OverallStatus,LastUpdatePostDate,StudyFirstPostDate,LeadSponsorName,Condition,InterventionName,Phase,BriefSummary"}
    url = "https://clinicaltrials.gov/api/v2/studies?" + urlencode(params)
    res = await cached_fetch(url, stats=stats, ttl_hours=12)
    data = json.loads(res.body)
    out = []
    for s in data.get("studies", []):
        ps = s.get("protocolSection", {})
        ident = ps.get("identificationModule", {})
        status = ps.get("statusModule", {})
        sponsor = ps.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("name")
        nct = ident.get("nctId")
        if not nct:
            continue
        upd = status.get("lastUpdatePostDateStruct", {}).get("date")
        if since and upd and upd < since.isoformat():
            continue
        out.append(item(
            "clinicaltrials", "ClinicalTrials.gov", "trial", ident.get("briefTitle", ""), f"https://clinicaltrials.gov/study/{nct}",
            published_at=status.get("studyFirstPostDateStruct", {}).get("date"), updated_at=upd,
            excerpt=f"Status: {status.get('overallStatus')}. Sponsor: {sponsor}. Phase: {', '.join(ps.get('designModule', {}).get('phases', []) or [])}. "
                    + (ps.get("descriptionModule", {}).get("briefSummary") or ""),
            meta={"nct_id": nct, "status": status.get("overallStatus"), "sponsor": sponsor,
                  "conditions": ps.get("conditionsModule", {}).get("conditions", [])[:5]},
            retrieved_at=res.retrieved_at, from_cache=res.from_cache,
        ))
    return out[:limit]


# ------------------------------------------------------------------ Europe PMC


async def search_europepmc(query: str, *, stats: CacheStats, limit: int = 10, since: date | None = None, raw: bool = False) -> list[dict]:
    since = since or (date.today() - timedelta(days=365))
    window = f"FIRST_PDATE:[{since.isoformat()} TO {date.today().isoformat()}]"
    q = f"{query} AND {window}" if raw else f"({query}) AND {window}"
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urlencode({"query": q, "format": "json", "pageSize": str(min(limit, 25)), "resultType": "core", "sort": "P_PDATE_D desc"})
    res = await cached_fetch(url, stats=stats, ttl_hours=24)
    data = json.loads(res.body)
    out = []
    for r in data.get("resultList", {}).get("result", []):
        link = f"https://europepmc.org/article/{r.get('source', 'MED')}/{r.get('id')}"
        if r.get("doi"):
            link = f"https://doi.org/{r['doi']}"
        out.append(item(
            "europepmc", "Europe PMC", "publication", r.get("title", ""), link,
            published_at=r.get("firstPublicationDate"), excerpt=(r.get("abstractText") or "")[:1200],
            meta={"journal": (r.get("journalInfo") or {}).get("journal", {}).get("title"), "authors": (r.get("authorString") or "")[:200], "pmid": r.get("pmid"), "is_preprint": r.get("source") == "PPR"},
            retrieved_at=res.retrieved_at, from_cache=res.from_cache,
        ))
    return out


# ------------------------------------------------------------- Federal Register


async def search_federal_register(query: str, *, stats: CacheStats, limit: int = 10, agencies: list[str] | None = None, since: date | None = None) -> list[dict]:
    params = [("conditions[term]", query), ("per_page", str(min(limit, 20))), ("order", "newest")]
    for a in agencies or ["food-and-drug-administration", "animal-and-plant-health-inspection-service"]:
        params.append(("conditions[agencies][]", a))
    if since:
        params.append(("conditions[publication_date][gte]", since.isoformat()))
    for f in ("title", "type", "abstract", "html_url", "publication_date", "agencies", "effective_on", "document_number", "comments_close_on"):
        params.append(("fields[]", f))
    url = "https://www.federalregister.gov/api/v1/documents.json?" + urlencode(params)
    res = await cached_fetch(url, stats=stats, ttl_hours=12)
    data = json.loads(res.body)
    out = []
    for r in data.get("results", []):
        agencies_ = ", ".join(a.get("name", "") for a in r.get("agencies", []) if a.get("name"))
        out.append(item(
            "federal_register", "Federal Register (US)", "regulatory", r.get("title", ""), r.get("html_url", ""),
            published_at=r.get("publication_date"), excerpt=r.get("abstract") or "",
            meta={"type": r.get("type"), "agencies": agencies_, "effective_on": r.get("effective_on"), "document_number": r.get("document_number"), "comments_close_on": r.get("comments_close_on")},
            retrieved_at=res.retrieved_at, from_cache=res.from_cache,
        ))
    return out


# ------------------------------------------------------------ FDA guidance index


FDA_GUIDANCE_URL = "https://www.fda.gov/files/api/datatables/static/search-for-guidance.json"


async def search_fda_guidance(terms: list[str], *, stats: CacheStats, centers: list[str], limit: int = 15, mode: str = "any") -> list[dict]:
    """FDA's public guidance-document index, filtered by center and keywords."""
    res = await cached_fetch(FDA_GUIDANCE_URL, stats=stats, ttl_hours=24)
    data = json.loads(res.body)
    out = []
    for r in data:
        center = clean_text(r.get("field_center", ""), 300)
        if centers and not any(c.lower() in center.lower() for c in centers):
            continue
        title_html = r.get("title", "")
        title = clean_text(title_html, 300)
        topics = clean_text(r.get("topics-product", "") + " " + r.get("field_topics", ""), 300)
        if terms and not matches(f"{title} {topics}", terms, mode):
            continue
        n_hits = sum(1 for t in terms if t.lower() in f"{title} {topics}".lower())
        m = re.search(r'href="([^"]+)"', title_html)
        url = urljoin("https://www.fda.gov", m.group(1)) if m else "https://www.fda.gov/regulatory-information/search-fda-guidance-documents"
        status = clean_text(r.get("field_final_guidance_1", ""), 30).lower()
        changed = re.search(r'datetime="([^"]+)"', r.get("changed", ""))
        out.append(item(
            "fda_guidance", "FDA guidance documents", "regulatory", title, url,
            published_at=iso_date(r.get("field_issue_datetime")), updated_at=changed.group(1)[:10] if changed else None,
            excerpt=f"Issuing office: {center}. Topics: {topics}. Type: {clean_text(r.get('field_communication_type', ''), 80)}. Status: {status}.",
            meta={"term_hits": n_hits, "center": center, "doc_status": "final" if "final" in status else "draft" if "draft" in status else "unknown",
                  "docket": clean_text(r.get("field_docket_number", ""), 60), "comment_open": "yes" in r.get("open-comment", "").lower()},
            retrieved_at=res.retrieved_at, from_cache=res.from_cache,
        ))
    # most term matches first, then most recent, so older but central guidance is not cut off
    out.sort(key=lambda x: (x["meta"]["term_hits"], x["published_at"] or ""), reverse=True)
    return out[:limit]


# ---------------------------------------------------------------- EMA documents


EMA_DOCS_URL = "https://www.ema.europa.eu/en/documents/report/documents-output-json-report_en.json"
EMA_GUIDANCE_TYPES = {"scientific-guideline", "regulatory-procedural-guideline", "other"}


async def search_ema_documents(terms: list[str], *, stats: CacheStats, veterinary: bool, limit: int = 15, mode: str = "any") -> list[dict]:
    """EMA's public document catalogue (JSON), filtered to guidelines."""
    res = await cached_fetch(EMA_DOCS_URL, stats=stats, ttl_hours=24, max_bytes=80 * 1024 * 1024, timeout=90)
    data = json.loads(res.body).get("data", [])
    out = []
    for r in data:
        if r.get("type") not in EMA_GUIDANCE_TYPES:
            continue
        name = r.get("name", "")
        ref = r.get("reference_number", "") or ""
        is_vet = "CVMP" in ref or "veterinary" in name.lower() or "VICH" in ref or "VICH" in name
        if veterinary != is_vet:
            continue
        if terms and not matches(name, terms, mode):
            continue
        n_hits = sum(1 for t in terms if t.lower() in name.lower())
        st = (r.get("status") or "unknown").lower()
        doc_status = "draft" if st.startswith("draft") else "final" if st == "adopted" else "unknown"
        out.append(item(
            "ema_documents", "European Medicines Agency", "regulatory", name, r.get("document_url", ""),
            published_at=r.get("first_published_date"), updated_at=r.get("last_updated_date"),
            excerpt=f"Reference: {ref}. Type: {r.get('type')}. EMA status: {r.get('status')}." + (f" Consultation: {r.get('consultation_date')}" if r.get("consultation_date") else ""),
            meta={"term_hits": n_hits, "reference": ref, "doc_status": doc_status, "ema_status": r.get("status"), "type": r.get("type")},
            retrieved_at=res.retrieved_at, from_cache=res.from_cache,
        ))
    out.sort(key=lambda x: (x["meta"]["term_hits"], x["updated_at"] or x["published_at"] or ""), reverse=True)
    return out[:limit]


# ------------------------------------------------------------------- RSS feeds


NEWS_FEEDS = {
    "fierce_biotech": ("Fierce Biotech", "https://feeds.feedburner.com/fiercebiotech"),
    "biopharma_dive": ("BioPharma Dive", "https://www.biopharmadive.com/feeds/news/"),
    "stat": ("STAT", "https://www.statnews.com/feed/"),
    "fda_press": ("FDA press releases", "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml"),
    "ema_news": ("EMA news", "https://www.ema.europa.eu/en/news.xml"),
    "vpn": ("Veterinary Practice News", "https://www.veterinarypracticenews.com/feed/"),
    "dvm360": ("dvm360", "https://www.dvm360.com/rss"),
}
ANIMAL_HEALTH_FEEDS = ("vpn", "dvm360")


async def fetch_feed(key: str, *, stats: CacheStats, ttl_hours: float = 6) -> list[dict]:
    name, url = NEWS_FEEDS[key]
    res = await cached_fetch(url, stats=stats, ttl_hours=ttl_hours, max_bytes=8 * 1024 * 1024)
    parsed = feedparser.parse(res.body)
    out = []
    for e in parsed.entries[:60]:
        link = e.get("link") or ""
        if not link.startswith(("http://", "https://")):
            continue
        pub = None
        for f in ("published_parsed", "updated_parsed"):
            if e.get(f):
                t = e.get(f)
                pub = f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}"
                break
        out.append(item(
            f"rss:{key}", name, "news", e.get("title", ""), link, published_at=pub,
            excerpt=e.get("summary", "") or e.get("description", ""), meta={"feed": key},
            retrieved_at=res.retrieved_at, from_cache=res.from_cache,
        ))
    return out


# -------------------------------------------------------------------- SEC EDGAR


ANIMAL_HEALTH_COMPANIES = {
    # name: (CIK, note) - US-listed companies with animal-health revenue reported to the SEC
    "Zoetis": ("0001555280", "Animal-health pure play; total revenue is animal health."),
    "Elanco Animal Health": ("0001739104", "Animal-health pure play; total revenue is animal health."),
    "Phibro Animal Health": ("0001069899", "Mostly livestock animal health and mineral nutrition; fiscal year ends June 30."),
}


async def sec_annual_revenue(cik: str, *, stats: CacheStats) -> list[dict]:
    """Annual revenue facts (10-K, full fiscal year) from SEC XBRL company facts."""
    headers = {"User-Agent": get_settings().sec_user_agent}
    out = []
    for concept in ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"):
        url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{concept}.json"
        try:
            res = await cached_fetch(url, stats=stats, ttl_hours=72, headers=headers)
        except Exception:  # noqa: BLE001 - concept not reported by this company
            continue
        data = json.loads(res.body)
        for f in data.get("units", {}).get("USD", []):
            if f.get("form") != "10-K" or f.get("fp") != "FY" or not f.get("start") or not f.get("end"):
                continue
            days = (date.fromisoformat(f["end"]) - date.fromisoformat(f["start"])).days
            if not 350 <= days <= 380:
                continue
            out.append({"concept": concept, "start": f["start"], "end": f["end"], "value": f["val"], "fy": f.get("fy"), "filed": f.get("filed"),
                        "accession": f.get("accn"), "entity": data.get("entityName"), "retrieved_at": res.retrieved_at, "from_cache": res.from_cache,
                        "source_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=10-K"})
        if out:
            break
    # keep the latest filing per fiscal period end
    best: dict[str, dict] = {}
    for f in out:
        if f["end"] not in best or f["filed"] > best[f["end"]]["filed"]:
            best[f["end"]] = f
    return sorted(best.values(), key=lambda x: x["end"])


async def sec_full_text(query: str, *, stats: CacheStats, forms: str = "10-K,8-K", limit: int = 10, since: date | None = None, cik: str | None = None) -> list[dict]:
    """SEC EDGAR full-text search (public filings), optionally limited to one company (CIK)."""
    since = since or (date.today() - timedelta(days=730))
    params = {"q": query, "forms": forms, "dateRange": "custom", "startdt": since.isoformat(), "enddt": date.today().isoformat()}
    if cik:
        params["ciks"] = cik
    url = "https://efts.sec.gov/LATEST/search-index?" + urlencode(params)
    res = await cached_fetch(url, stats=stats, ttl_hours=24, headers={"User-Agent": get_settings().sec_user_agent})
    data = json.loads(res.body)
    out = []
    for h in data.get("hits", {}).get("hits", [])[:limit]:
        src = h.get("_source", {})
        adsh = (h.get("_id") or "").split(":")[0]
        ciks = src.get("ciks") or []
        fname = (h.get("_id") or ":").split(":")[1]
        if not ciks or not adsh:
            continue
        link = f"https://www.sec.gov/Archives/edgar/data/{int(ciks[0])}/{adsh.replace('-', '')}/{fname}"
        out.append(item(
            "sec_fulltext", "SEC EDGAR", "filing", f"{', '.join(src.get('display_names', [])[:1])} - {src.get('form')} ({src.get('file_date')})", link,
            published_at=src.get("file_date"), excerpt=f"Form {src.get('form')} filed {src.get('file_date')}; matched query terms in filing text.",
            meta={"form": src.get("form"), "company": (src.get("display_names") or [""])[0], "period": src.get("period_ending")},
            retrieved_at=res.retrieved_at, from_cache=res.from_cache,
        ))
    return out


# ----------------------------------------------------- official index pages (CN/JP/KR)


INDEX_PAGES = {
    # key: (authority, jurisdiction, language, url, keyword regex)
    "mara_notices": ("Ministry of Agriculture and Rural Affairs (MARA) - notices", "CN", "zh", "https://www.moa.gov.cn/gk/tzgg_1/", r"兽药|兽医|动物|生物制品|疫苗"),
    "nval": ("MAFF National Veterinary Assay Laboratory (NVAL)", "JP", "ja", "https://www.maff.go.jp/nval/", r"動物用医薬品|承認|ガイドライン|指針|生物学的製剤|抗体"),
    "apqa": ("Animal and Plant Quarantine Agency (APQA)", "KR", "ko", "https://www.apqa.go.kr/", r"동물용의약품|동물용 의약품|백신|고시|허가|가이드"),
    "pmda": ("PMDA (Japan, human medicines)", "JP", "en", "https://www.pmda.go.jp/english/", r"guid|notification|regulat|biolog|antibod|oncolog"),
    "mfds_guideline": ("MFDS (Korea, human medicines) - guidelines", "KR", "en", "https://www.mfds.go.kr/eng/brd/m_1127/list.do", r"guid|biolog|antibod|clinical|quality|manufactur|drug"),
}


def _decode(body: bytes, content_type: str) -> str:
    enc = None
    if "charset=" in content_type:
        enc = content_type.split("charset=")[-1].split(";")[0].strip()
    if not enc:
        m = re.search(rb'charset=["\']?([\w-]+)', body[:4000])
        enc = m.group(1).decode() if m else "utf-8"
    try:
        return body.decode(enc, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


async def scan_index_page(key: str, *, stats: CacheStats, limit: int = 15) -> list[dict]:
    authority, jur, lang, url, pattern = INDEX_PAGES[key]
    res = await cached_fetch(url, stats=stats, ttl_hours=24, timeout=30)
    soup = BeautifulSoup(_decode(res.body, res.content_type), "html.parser")
    rx = re.compile(pattern, re.I)
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        href = urljoin(res.final_url, a["href"])
        if not text or len(text) < 6 or not href.startswith(("http://", "https://")) or href in seen:
            continue
        if not rx.search(text):
            continue
        seen.add(href)
        m = re.search(r"(20\d{2})(\d{2})(\d{2})", href) or re.search(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})", (a.parent.get_text(" ", strip=True) if a.parent else ""))
        pub = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None
        out.append(item(
            f"index:{key}", authority, "regulatory", text, href, published_at=pub, language=lang,
            original_title=text if lang != "en" else None,
            excerpt=f"Link listed on the official {authority} page {url}. Title in original language; open the source for content.",
            meta={"jurisdiction": jur, "index_url": url},
            retrieved_at=res.retrieved_at, from_cache=res.from_cache,
        ))
    return out[:limit]


async def fetch_document_text(url: str, *, stats: CacheStats, max_chars: int = 12000) -> dict:
    """Fetch a public HTML or PDF document and return plain text (untrusted)."""
    res = await cached_fetch(url, stats=stats, ttl_hours=72, max_bytes=15 * 1024 * 1024)
    ctype = res.content_type.lower()
    text = ""
    if "pdf" in ctype or res.body[:5] == b"%PDF-":
        import io

        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(res.body))
            parts = []
            for i, page in enumerate(reader.pages[:25]):
                parts.append(f"[page {i + 1}] " + (page.extract_text() or ""))
                if sum(len(p) for p in parts) > max_chars:
                    break
            text = "\n".join(parts)
        except Exception as exc:  # noqa: BLE001
            text = f"[PDF text extraction failed: {type(exc).__name__}]"
    else:
        soup = BeautifulSoup(_decode(res.body, res.content_type), "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "form"]):
            tag.decompose()
        main = soup.find("main") or soup.find("article") or soup.body or soup
        text = re.sub(r"\n\s*\n+", "\n", main.get_text("\n", strip=True))
    return {"url": url, "final_url": res.final_url, "content_type": ctype, "text": text[:max_chars], "sha256": res.sha256,
            "retrieved_at": res.retrieved_at, "from_cache": res.from_cache, "truncated": len(text) > max_chars}


__all__ = [
    "search_clinicaltrials", "search_europepmc", "search_federal_register", "search_fda_guidance", "search_ema_documents",
    "fetch_feed", "NEWS_FEEDS", "ANIMAL_HEALTH_FEEDS", "sec_annual_revenue", "sec_full_text", "ANIMAL_HEALTH_COMPANIES",
    "scan_index_page", "INDEX_PAGES", "fetch_document_text", "quote",
]
