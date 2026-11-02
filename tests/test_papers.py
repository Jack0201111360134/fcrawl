"""fcrawl papers: Scholar (gateway and direct) + Research Index, merge/dedup, pdf lookup.
All HTTP is faked; nothing leaves the machine."""

from __future__ import annotations

import json

import click
import pytest
from click.testing import CliRunner

from fcrawl.cli import cli
from fcrawl.commands import papers as P
from fcrawl.utils import cache as cache_mod


class R:
    def __init__(self, status=200, body=None, headers=None, text=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = text if text is not None else json.dumps(body)

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


SCHOLAR_ITEMS = [
    {"title": "Attention Is All You Need", "link": "https://arxiv.org/abs/1706.03762v7",
     "publicationInfo": "A Vaswani, N Shazeer - NeurIPS, 2017", "snippet": "The dominant sequence…",
     "year": 2017, "citedBy": 200000, "pdfUrl": "https://arxiv.org/pdf/1706.03762"},
    {"title": "A CMOS UVLO circuit", "link": "https://ieeexplore.ieee.org/abstract/document/123/",
     "publicationInfo": "X Li - IEEE JSSC, 2016", "snippet": "low quiescent…", "year": 2016, "citedBy": 12},
    {"title": "Some Springer paper", "link": "https://link.springer.com/article/10.1007/s10470-019-01556-1",
     "year": 2019, "citedBy": 3},
]
INDEX_RESULTS = [
    {"paperId": "8319", "primaryId": "arxiv:1706.03762", "ids": {"arxiv": ["1706.03762"]},
     "title": "Attention is all you need", "abstract": "The dominant sequence transduction models " * 20,
     "score": 0.9},
    {"paperId": "77", "primaryId": "pmid:34515826", "ids": {"pmid": ["34515826"], "doi": ["10.1007/S00294-021-01211-1"]},
     "title": "Off-target effects of base editors", "abstract": "Base editors…", "score": 0.5},
]


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Gateway mode, fresh cache dir, every HTTP call recorded."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".fcrawlrc").write_text(json.dumps({"api_url": "https://gw.example", "gateway_token": "fgw_t_secret"}))
    monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.delenv("FCRAWL_GATEWAY_TOKEN", raising=False)
    calls: dict[str, list] = {"post": [], "get": []}
    state = {"scholar": lambda payload, page: R(200, {"organic": SCHOLAR_ITEMS if page == 1 else [],
                                                       "gw": {"gwType": "scholar", "gwCreditsUsed": 1, "gwCached": False}}),
             "index": lambda url, params: R(200, {"success": True, "results": INDEX_RESULTS})}

    def post(url, headers=None, json=None, timeout=None):
        calls["post"].append((url, dict(headers or {}), json))
        return state["scholar"](json, json.get("page", 1))

    def get(url, params=None, headers=None, timeout=None):
        calls["get"].append((url, dict(params or {}), dict(headers or {})))
        return state["index"](url, params or {})

    monkeypatch.setattr(P.requests, "post", post)
    monkeypatch.setattr(P.requests, "get", get)
    return calls, state, tmp_path


def run(*args):
    return CliRunner().invoke(cli, ["papers", *args])  # .output = stdout + stderr, .stdout alone


def stdout_json(res):
    """--json: stdout must be exactly one JSON document (notes and credits go to stderr)."""
    return json.loads(res.stdout)


# --- ids -----------------------------------------------------------------------


@pytest.mark.parametrize("raw,want", [
    ("arxiv:1706.03762", "arxiv:1706.03762"),
    ("1706.03762v5", "arxiv:1706.03762v5"),
    ("hep-th/9901001", "arxiv:hep-th/9901001"),
    ("https://arxiv.org/abs/1706.03762", "arxiv:1706.03762"),
    ("https://arxiv.org/pdf/1706.03762v2.pdf", "arxiv:1706.03762v2"),
    ("10.1038/nature14539", "doi:10.1038/nature14539"),
    ("doi:10.1038/nature14539", "doi:10.1038/nature14539"),
    ("https://doi.org/10.1109/JSSC.2010.2042254", "doi:10.1109/jssc.2010.2042254"),
    ("https://link.springer.com/content/pdf/10.1007/s10470-019-01556-1.pdf", "doi:10.1007/s10470-019-01556-1"),
    ("PMC13172344", "pmcid:PMC13172344"),
    ("pmcid:13172344", "pmcid:PMC13172344"),
    ("https://pmc.ncbi.nlm.nih.gov/articles/PMC123/", "pmcid:PMC123"),
    ("https://pubmed.ncbi.nlm.nih.gov/34515826/", "pmid:34515826"),
    ("34515826", "pmid:34515826"),
    ("8319239866974784291", "8319239866974784291"),
])
def test_normalize_id(raw, want):
    assert P.normalize_id(raw) == want


@pytest.mark.parametrize("raw", ["", "hello world", "https://example.com/page", "x" * 400, "arxiv:", "a\nb"])
def test_normalize_id_rejects(raw):
    with pytest.raises(click.BadParameter):
        P.normalize_id(raw)


def test_doi_slash_is_encoded_in_the_path():
    assert P.id_path("doi:10.1038/nature14539") == "doi:10.1038%2Fnature14539"
    assert P.id_path("arxiv:1706.03762") == "arxiv:1706.03762"


def test_parse_bound():
    assert P.parse_bound("2024", end=False, hint="--since") == (2024, "2024-01-01")
    assert P.parse_bound("2024", end=True, hint="--until") == (2024, "2024-12-31")
    assert P.parse_bound("2024-05-01", end=False, hint="--since") == (2024, "2024-05-01")
    for bad in ("24", "2024-13-01", "last year", "1500"):
        with pytest.raises(click.BadParameter):
            P.parse_bound(bad, end=False, hint="--since")


# --- merge -----------------------------------------------------------------------


def test_merge_dedups_by_arxiv_id_and_keeps_both_engines_facts():
    s = [P.from_scholar(it) for it in SCHOLAR_ITEMS]
    i = [P.from_index(it) for it in INDEX_RESULTS]
    out = P.merge(s, i)
    assert len(out) == 4
    att = out[0]
    assert att["sources"] == ["scholar", "index"]
    assert att["citedBy"] == 200000 and att["year"] == 2017  # from Scholar
    assert att["abstract"].startswith("The dominant sequence transduction")  # from the index
    assert att["id"] == "arxiv:1706.03762" and att["ids"]["arxiv"] == "1706.03762"  # v7 stripped
    # interleaved by rank: scholar 1, index 1 (merged), scholar 2, index 2, scholar 3
    assert [p["title"][:10] for p in out] == ["Attention ", "A CMOS UVL", "Off-target", "Some Sprin"]
    # DOI lowercased from the index's ids, taken from Springer's URL for Scholar
    assert out[2]["ids"]["doi"] == "10.1007/s00294-021-01211-1"
    assert out[3]["ids"]["doi"] == "10.1007/s10470-019-01556-1" and out[3]["id"] == "doi:10.1007/s10470-019-01556-1"


def test_merge_by_title_only_across_engines():
    a = P.from_scholar({"title": "Deep Residual Learning for Image Recognition", "link": "https://x.org/a", "year": 2016})
    b = P.from_index({"primaryId": "pmid:1", "ids": {"pmid": ["1"]}, "title": "Deep residual learning for image recognition."})
    c = P.from_scholar({"title": "Deep Residual Learning for Image Recognition", "link": "https://y.org/b", "year": 2016})
    out = P.merge([a, c], [b])
    # a and b fold (different engines); c stays separate (same engine: maybe a different paper)
    assert len(out) == 2 and out[0]["sources"] == ["scholar", "index"]
    short1 = P.from_scholar({"title": "Point transformer", "link": "https://p/1", "year": 2021})
    short2 = P.from_index({"primaryId": "arxiv:2012.09164", "ids": {}, "title": "Point Transformer"})
    assert len(P.merge([short1], [short2])) == 2  # short titles never fold


def test_sort_citations_and_date():
    ps = [{"citedBy": None, "year": 2020}, {"citedBy": 5, "year": None}, {"citedBy": 50, "year": 2024}]
    assert [p["citedBy"] for p in P.sort_papers(list(ps), "citations")] == [50, 5, None]
    assert [p["year"] for p in P.sort_papers(list(ps), "date")] == [2024, 2020, None]


# --- search command ---------------------------------------------------------------


def test_search_gateway_sends_scholar_type_and_index_filters(env):
    calls, state, _ = env
    res = run("transformer attention", "--since", "2020", "--until", "2024", "--category", "cs.LG",
              "--authors", "Vaswani")
    assert res.exit_code == 0, res.output
    url, headers, payload = calls["post"][0]
    assert url == "https://gw.example/gw/search"
    assert payload == {"q": "transformer attention", "num": 10, "type": "scholar", "as_ylo": 2020, "as_yhi": 2024}
    assert headers["X-API-KEY"] == "fgw_t_secret"
    gurl, params, gheaders = calls["get"][0]
    assert gurl == P.RESEARCH_ENDPOINT
    assert params == {"query": "transformer attention", "k": 10, "authors": "Vaswani", "categories": "cs.LG",
                      "from": "2020-01-01", "to": "2024-12-31"}
    assert "Authorization" not in gheaders  # the gateway token never goes to Firecrawl
    assert "credits: 1 Serper (Scholar)" in res.output
    assert "scholar+index" in res.output and "cited 200000" in res.output
    assert "fcrawl scrape https://arxiv.org/pdf/1706.03762 --save-temp" in res.output
    assert "fcrawl papers read arxiv:1706.03762" in res.output
    assert "fgw_t_secret" not in res.output


def test_search_is_the_default_subcommand_and_caches(env):
    calls, _, _ = env
    assert run("q one").exit_code == 0
    assert run("search", "q one").exit_code == 0
    assert len(calls["post"]) == 1 and len(calls["get"]) == 1  # second run: local cache
    assert run("q one", "--no-cache").exit_code == 0
    assert calls["post"][-1][1].get("X-No-Cache") == "1" and len(calls["get"]) == 2


def test_search_scholar_pages_cost_one_credit_each(env):
    calls, state, _ = env
    page = [dict(SCHOLAR_ITEMS[1], title=f"T{i}", link=f"https://e/{i}") for i in range(10)]
    state["scholar"] = lambda payload, n: R(200, {"organic": page if n < 3 else page[:4],
                                                  "gw": {"gwType": "scholar", "gwCreditsUsed": 1}})
    res = run("q", "--engine", "scholar", "-l", "30", "--json")
    assert res.exit_code == 0, res.output
    assert [c[2].get("page", 1) for c in calls["post"]] == [1, 2, 3]
    data = stdout_json(res)
    assert data["meta"]["scholarCredits"] == 3 and not calls["get"]


def test_search_direct_mode_uses_serper_scholar(env, monkeypatch):
    calls, _, tmp = env
    (tmp / ".fcrawlrc").write_text(json.dumps({"serper_api_key": "serper-direct"}))
    state_payload = {}

    def post(url, headers=None, json=None, timeout=None):
        calls["post"].append((url, dict(headers or {}), json))
        state_payload.update(json)
        return R(200, {"organic": SCHOLAR_ITEMS, "credits": 1})

    monkeypatch.setattr(P.requests, "post", post)
    res = run("q", "--engine", "scholar")
    assert res.exit_code == 0, res.output
    assert calls["post"][0][0] == "https://google.serper.dev/scholar"
    assert calls["post"][0][1]["X-API-KEY"] == "serper-direct" and "type" not in state_payload


def test_search_one_engine_failing_keeps_the_other(env):
    calls, state, _ = env
    state["scholar"] = lambda payload, page: R(429, {"error": "personal_quota: used 200/200"}, headers={"Retry-After": "300"})
    res = run("q")
    assert res.exit_code == 0, res.output
    assert "scholar: Scholar error 429: personal_quota" in res.output and "retry after 300s" in res.output
    assert "Found 2 papers" in res.output and "(index)" in res.output


def test_search_old_gateway_says_update(env):
    calls, state, _ = env
    state["scholar"] = lambda payload, page: R(400, {"error": "bad_request: type must be search or news"})
    res = run("q", "--engine", "scholar")
    assert res.exit_code != 0 and "does not support Scholar yet" in res.output


def test_search_gateway_answering_web_results_is_refused(env):
    calls, state, _ = env
    state["scholar"] = lambda payload, page: R(200, {"organic": SCHOLAR_ITEMS, "gw": {"gwType": "search"}})
    res = run("q", "--engine", "scholar")
    assert res.exit_code != 0 and "answered with web results" in res.output


def test_search_both_fail_aborts(env):
    calls, state, _ = env
    state["scholar"] = lambda payload, page: R(503, {"error": "pool_exhausted: Serper rejected"})
    state["index"] = lambda url, params: R(429, {"success": False})
    res = run("q")
    assert res.exit_code != 0
    assert "No engine answered" in res.output and "rate limit" in res.output


def test_search_input_checks(env):
    calls, _, _ = env
    assert run("q", "--since", "2025", "--until", "2020").exit_code != 0
    assert run("q", "-l", "0").exit_code != 0
    assert run(" ").exit_code != 0
    assert not calls["post"] and not calls["get"]


def test_search_json_shape(env):
    res = run("q", "--json")
    data = stdout_json(res)
    assert data["engines"] == ["scholar", "index"]
    first = data["results"][0]
    assert set(first) >= {"title", "year", "venue", "citedBy", "ids", "id", "links", "snippet", "abstract", "sources"}


# --- read / show / related ----------------------------------------------------------


def test_read_encodes_doi_and_prints_passages(env):
    calls, state, _ = env
    state["index"] = lambda url, params: R(200, {"success": True, "paper": {"title": "T"}, "paperId": "1",
                                                 "query": params.get("query"),
                                                 "passages": [{"text": "passage one", "score": 0.5}]})
    res = run("read", "doi:10.1038/nature14539", "-q", "what?", "-k", "2")
    assert res.exit_code == 0, res.output
    url, params, _ = calls["get"][0]
    assert url.endswith("/papers/doi:10.1038%2Fnature14539") and params == {"query": "what?", "k": 2}
    assert "passage one" in res.output and "score 0.500" in res.output


def test_read_not_in_index(env):
    calls, state, _ = env
    state["index"] = lambda url, params: R(404, {"success": False, "code": "NOT_FOUND"})
    res = run("read", "doi:10.1109/jssc.2010.2042254", "-q", "x")
    assert res.exit_code != 0 and "not in the Research Index" in res.output


def test_read_without_passages_points_elsewhere(env):
    calls, state, _ = env
    state["index"] = lambda url, params: R(200, {"success": True, "paper": {"title": "T"}, "passages": []})
    res = run("read", "pmid:1", "-q", "x")
    assert res.exit_code == 0 and "No full-text passages" in res.output and "papers pdf pmid:1" in res.output


def test_related_defaults_intent_to_title(env):
    calls, state, _ = env

    def index(url, params):
        if url.endswith("/similar"):
            return R(200, {"success": True, "results": INDEX_RESULTS[1:], "poolSize": 1, "truncated": False})
        return R(200, {"success": True, "paper": {"title": "Attention Is All You Need", "ids": {"arxiv": ["1706.03762"]}}})

    state["index"] = index
    res = run("related", "1706.03762", "--mode", "citers", "-l", "5")
    assert res.exit_code == 0, res.output
    url, params, _ = calls["get"][1]
    assert url.endswith("/papers/arxiv:1706.03762/similar")
    assert params == {"intent": "Attention Is All You Need", "mode": "citers", "k": 5}
    assert "Off-target effects" in res.output


def test_show_falls_back_to_openalex_for_paywalled_doi(env):
    calls, state, _ = env

    def index(url, params):
        if "openalex" in url:
            return R(200, {"title": "A 10-bit SAR ADC", "publication_year": 2010, "cited_by_count": 1330,
                           "ids": {"doi": "https://doi.org/10.1109/jssc.2010.2042254"},
                           "open_access": {"oa_status": "closed"},
                           "abstract_inverted_index": {"This": [0], "ADC": [2], "SAR": [1]},
                           "primary_location": {"source": {"display_name": "IEEE JSSC"}}, "locations": []})
        return R(404, {"success": False})

    state["index"] = index
    res = run("show", "10.1109/JSSC.2010.2042254")
    assert res.exit_code == 0, res.output
    assert "via openalex" in res.output and "This SAR ADC" in res.output and "open access: closed" in res.output
    assert "papers pdf doi:10.1109/jssc.2010.2042254" in res.output


# --- pdf ------------------------------------------------------------------------------


def test_host_kind():
    assert P.host_kind("https://arxiv.org/pdf/1") == "repository"
    assert P.host_kind("https://www.ncbi.nlm.nih.gov/pmc/articles/1") == "repository"
    assert P.host_kind("https://www.mdpi.com/x.pdf") == "publisher-oa"
    assert P.host_kind("https://sscas.ee.ncku.edu.tw/web/files/a.pdf") == "author-site"
    assert P.host_kind("https://www.cs.ox.ac.uk/a.pdf") == "author-site"
    assert P.host_kind("https://www.researchgate.net/x") == "social-upload"
    assert P.host_kind("https://evil-arxiv.org.example/x.pdf") == "unknown"
    assert P.host_kind("https://notarxiv.org/x.pdf") == "unknown"
    assert P.host_kind("ftp://arxiv.org/x") == "unknown"


def test_pdf_arxiv_needs_no_network(env):
    calls, _, _ = env
    res = run("pdf", "arxiv:1706.03762")
    assert res.exit_code == 0 and "https://arxiv.org/pdf/1706.03762" in res.output
    assert not calls["post"]  # no Scholar credit


def test_pdf_openalex_oa_locations_ranked(env):
    calls, state, _ = env
    state["index"] = lambda url, params: R(200, {
        "title": "AlphaFold", "publication_year": 2021,
        "ids": {"doi": "https://doi.org/10.1038/s41586-021-03819-2", "pmcid": "https://www.ncbi.nlm.nih.gov/pmc/articles/8371605"},
        "open_access": {"oa_status": "hybrid"},
        "locations": [
            {"is_oa": True, "pdf_url": "https://www.nature.com/articles/s41586-021-03819-2.pdf",
             "landing_page_url": "https://doi.org/10.1038/s41586-021-03819-2", "source": {"type": "journal"},
             "version": "publishedVersion", "license": "cc-by"},
            {"is_oa": False, "landing_page_url": "https://pubmed.ncbi.nlm.nih.gov/1", "source": {"type": "repository"}},
        ]})
    res = run("pdf", "doi:10.1038/s41586-021-03819-2", "--json")
    data = stdout_json(res)
    urls = [c["url"] for c in data["candidates"]]
    assert urls[0] == "https://www.nature.com/articles/s41586-021-03819-2.pdf"
    assert "https://pubmed.ncbi.nlm.nih.gov/1" not in urls  # not OA
    assert "https://pmc.ncbi.nlm.nih.gov/articles/PMC8371605/" in urls
    assert not calls["post"]


def test_pdf_closed_paper_filters_scholar_pdf_hosts(env):
    calls, state, _ = env

    def index(url, params):
        if "openalex" in url:
            return R(200, {"title": "A 10-bit 50-MS/s SAR ADC", "ids": {"doi": "https://doi.org/10.1109/jssc.2010.2042254"},
                           "open_access": {"oa_status": "closed"}, "locations": []})
        return R(429, {"message": "Too Many Requests"})  # Semantic Scholar keyless

    state["index"] = index
    state["scholar"] = lambda payload, page: R(200, {"organic": [
        {"title": "A 10-bit 50-MS/s SAR ADC", "link": "https://ieeexplore.ieee.org/document/5437496",
         "pdfUrl": "https://sscas.ee.ncku.edu.tw/web/files/2010JSSC.pdf"},
        {"title": "A 10-bit 50-MS/s SAR ADC", "link": "https://x", "pdfUrl": "https://pirate-papers.example/f.pdf"},
        {"title": "A 10-bit 50-MS/s SAR ADC", "link": "https://y", "pdfUrl": "https://www.researchgate.net/f.pdf"},
        {"title": "Something else", "link": "https://z", "pdfUrl": "https://arxiv.org/pdf/2"},
    ], "gw": {"gwType": "scholar", "gwCreditsUsed": 1}})
    res = run("pdf", "doi:10.1109/JSSC.2010.2042254")
    assert res.exit_code == 0, res.output
    assert calls["post"][0][2]["q"] == "A 10-bit 50-MS/s SAR ADC"
    out = res.output
    assert "[author-site] https://sscas.ee.ncku.edu.tw" in out
    assert "[social-upload] https://www.researchgate.net/f.pdf" in out and "copyright unclear" in out
    assert "pirate-papers" not in out and "1 PDF link(s) from unknown hosts not shown" in out
    assert "arxiv.org/pdf/2" not in out  # a different paper's PDF
    assert "read it: fcrawl scrape https://sscas.ee.ncku.edu.tw" in out  # never the social upload first
    assert "Semantic Scholar: rate limited" in out and "credits: 1 Serper" in out


def test_pdf_nothing_found_says_so(env):
    calls, state, _ = env
    state["index"] = lambda url, params: (R(200, {"title": "Closed", "ids": {}, "open_access": {"oa_status": "closed"},
                                                  "locations": []}) if "openalex" in url else R(404, {}))
    res = run("pdf", "doi:10.1016/j.mejo.2018.01.001", "--no-scholar")
    assert res.exit_code == 0
    assert "No legal free copy found" in res.output and "https://doi.org/10.1016/j.mejo.2018.01.001" in res.output
    assert "own school or library access" in res.output and not calls["post"]


def test_no_shadow_libraries_anywhere():
    import inspect
    src = inspect.getsource(P).lower()
    for name in ("sci-hub", "scihub", "libgen", "annas-archive", "anna's archive"):
        assert name not in src


# --- review round 1 ----------------------------------------------------------------


def test_r1_json_stdout_is_pure_json_with_warnings(env):
    calls, state, _ = env
    state["scholar"] = lambda payload, page: R(503, {"error": "pool_exhausted: [/red] Serper"})
    res = run("q", "--json")
    data = stdout_json(res)
    assert data["meta"]["errors"]["scholar"].startswith("Scholar error 503")
    assert "credits:" in res.stderr and "scholar:" in res.stderr  # markup in the message did not crash rich


def test_r1_pdf_json_stdout_is_pure_json(env):
    calls, state, _ = env
    state["index"] = lambda url, params: (R(200, {"title": "Closed one", "ids": {}, "open_access": {}, "locations": []})
                                          if "openalex" in url else R(429, {}))
    state["scholar"] = lambda payload, page: R(200, {"organic": [], "gw": {"gwType": "scholar", "gwCreditsUsed": 1}})
    res = run("pdf", "doi:10.1/x", "--json")
    assert stdout_json(res)["scholarCredits"] == 1 and "credits: 1" in res.stderr


def test_r1_credits_survive_a_later_page_failure(env):
    calls, state, _ = env
    full = [dict(SCHOLAR_ITEMS[1], title=f"T{i}", link=f"https://e/{i}") for i in range(10)]

    def scholar(payload, page):
        if page == 1:
            return R(200, {"organic": full, "gw": {"gwType": "scholar", "gwCreditsUsed": 1}})
        return R(504, {"error": "upstream_error: Serper timed out", "details": {"creditsUsed": 1}})

    state["scholar"] = scholar
    res = run("q", "-l", "20", "--json")
    data = stdout_json(res)
    assert data["meta"]["scholarCredits"] == 2  # page 1 + the billed page-2 timeout
    assert "credits: 2 Serper" in res.stderr


def test_r1_gateway_cache_hit_is_free(env):
    calls, state, _ = env
    # an older gateway's cache hit: no gwCreditsUsed, top-level credits still 1
    state["scholar"] = lambda payload, page: R(200, {"organic": SCHOLAR_ITEMS, "credits": 1,
                                                       "gw": {"gwType": "scholar", "gwCached": True}})
    res = run("q", "--engine", "scholar")
    assert "credits: 0 Serper (Scholar), cached" in res.stderr


def test_r1_pdf_needs_title_or_both_dois(env):
    calls, state, _ = env
    state["index"] = lambda url, params: (R(200, {"title": "Gut microbes and sleep", "ids": {"pmid": "https://pubmed.ncbi.nlm.nih.gov/5"},
                                                  "open_access": {}, "locations": []})
                                          if "openalex" in url else R(404, {}))
    state["scholar"] = lambda payload, page: R(200, {"organic": [
        {"title": "A different paper", "link": "https://x.edu/a", "pdfUrl": "https://arxiv.org/pdf/9"}],
        "gw": {"gwType": "scholar", "gwCreditsUsed": 1}})
    data = stdout_json(run("pdf", "pmid:5", "--json"))
    assert data["found"] is False and data["candidates"] == []


@pytest.mark.parametrize("raw,want", [
    ("https://doi.org/10.1002/(SICI)1099-0844(199912)17:4%3C290::AID-CBF849%3E3.0.CO;2-P",
     "doi:10.1002/(sici)1099-0844(199912)17:4<290::aid-cbf849>3.0.co;2-p"),
    ("https://arxiv.org/abs/1706.03762?context=cs.LG", "arxiv:1706.03762"),
    ("https://arxiv.org/pdf/1706.03762v2?download=1", "arxiv:1706.03762v2"),
    ("https://arxiv.org/abs/1706.03762#section", "arxiv:1706.03762"),
    ("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8371605/", "pmcid:PMC8371605"),
    ("https://onlinelibrary.wiley.com/doi/full/10.1002/adma.202001234", "doi:10.1002/adma.202001234"),
    ("https://doi.org/10.1016/S0140-6736(20)30183-5", "doi:10.1016/s0140-6736(20)30183-5"),
])
def test_r1_normalize_id_urls(raw, want):
    assert P.normalize_id(raw) == want


def test_r1_scholar_pubmed_links_dedup_with_index():
    s = P.from_scholar({"title": "Short", "link": "https://pubmed.ncbi.nlm.nih.gov/34515826/"})
    s2 = P.from_scholar({"title": "Other", "link": "https://pmc.ncbi.nlm.nih.gov/articles/PMC13172344/"})
    i = [P.from_index(it) for it in INDEX_RESULTS[1:]]
    i.append(P.from_index({"primaryId": "pmcid:PMC13172344", "ids": {"pmcid": ["PMC13172344"]}, "title": "Long title"}))
    out = P.merge([s, s2], i)
    assert len(out) == 2 and all(p["sources"] == ["scholar", "index"] for p in out)


def test_r1_merge_consolidates_through_a_linking_record():
    a = P.from_scholar({"title": "Paper A", "link": "https://doi.org/10.1145/12345.6789"})
    b = P.from_index({"primaryId": "arxiv:2001.00001", "ids": {"arxiv": ["2001.00001"]}, "title": "Preprint B"})
    link = P.from_scholar({"title": "Paper A again", "link": "https://doi.org/10.1145/12345.6789",
                           "pdfUrl": "https://arxiv.org/pdf/2001.00001"})
    out = P.merge([a, link], [b])
    assert len(out) == 1
    assert out[0]["ids"] == {"doi": "10.1145/12345.6789", "arxiv": "2001.00001"} and out[0]["sources"] == ["scholar", "index"]


def test_r1_terminal_controls_stripped_and_markup_safe(env):
    calls, state, _ = env

    def index(url, params):
        if url.endswith("/similar"):
            return R(200, {"success": True, "results": [{"primaryId": "pmid:1", "ids": {}, "title": "T\x1b]52;c;ZXZpbA==\x07x",
                                                         "abstract": "a"}]})
        return R(200, {"success": True, "paper": {"title": "[/bold] broken [red"}})

    state["index"] = index
    res = run("related", "pmid:1")
    assert res.exit_code == 0, res.output
    assert "\x1b" not in res.stdout and "\x07" not in res.stdout and "T]52;c;ZXZpbA==x" in res.stdout
    assert "[/bold] broken" in res.stderr


# --- review round 2 ----------------------------------------------------------------


def test_r2_credits_shown_even_when_every_engine_failed(env):
    calls, state, _ = env
    full = [dict(SCHOLAR_ITEMS[1], title=f"T{i}", link=f"https://e/{i}") for i in range(10)]
    state["scholar"] = lambda payload, page: (
        R(200, {"organic": full, "gw": {"gwType": "scholar", "gwCreditsUsed": 1}}) if page == 1
        else R(504, {"error": "upstream_error: Serper timed out", "details": {"creditsUsed": 1}}))
    res = run("q", "--engine", "scholar", "-l", "20")
    assert res.exit_code != 0 and "credits: 2 Serper" in res.stderr and not res.stdout.strip()


def test_r2_merged_record_keeps_every_doi_alias():
    pre = P.from_scholar({"title": "Preprint title here", "link": "https://arxiv.org/abs/2001.00001",
                          "pdfUrl": "https://doi.org/10.48550/arxiv.2001.00001"})
    pub = P.from_index({"primaryId": "arxiv:2001.00001", "ids": {"arxiv": ["2001.00001"], "doi": ["10.1145/3000.1"]},
                        "title": "Published title"})
    later = P.from_scholar({"title": "Venue version", "link": "https://dl.acm.org/doi/10.1145/3000.1"})
    out = P.merge([pre, later], [pub])
    assert len(out) == 1 and "_aliases" not in out[0]
    assert out[0]["ids"]["doi"] == "10.48550/arxiv.2001.00001"  # first seen stays the public one


@pytest.mark.parametrize("raw,want", [
    ("https://europepmc.org/article/PMC/PMC8371605", "pmcid:PMC8371605"),
    ("https://europepmc.org/article/MED/34515826", "pmid:34515826"),
    ("https://europepmc.org/abstract/MED/34515826", "pmid:34515826"),
])
def test_r2_europe_pmc_routes(raw, want):
    assert P.normalize_id(raw) == want


def test_r2_no_terminal_controls_anywhere_on_stdout(env):
    calls, state, _ = env
    bad = "\x1b]52;c;ZXZpbA==\x07"
    state["scholar"] = lambda payload, page: R(200, {"organic": [
        {"title": "T" + bad, "link": "https://e.org/x" + bad, "pdfUrl": "https://arxiv.org/pdf/1" + bad,
         "publicationInfo": "V" + bad, "snippet": "s" + bad}], "gw": {"gwType": "scholar", "gwCreditsUsed": 1}})
    state["index"] = lambda url, params: R(200, {"success": True, "results": [
        {"primaryId": "pmid:" + bad, "ids": {}, "title": "I" + bad, "abstract": "a" + bad}]})
    res = run("q")
    assert res.exit_code == 0, res.output
    assert "\x1b" not in res.stdout and "\x07" not in res.stdout


def test_r2_pdf_notes_on_stderr(env):
    calls, state, _ = env
    state["index"] = lambda url, params: (R(200, {"title": "Closed", "ids": {}, "open_access": {"oa_status": "closed"},
                                                  "locations": []}) if "openalex" in url else R(404, {}))
    res = run("pdf", "doi:10.1016/j.mejo.2018.01.001", "--no-scholar")
    assert "OpenAlex: closed" in res.stderr and "OpenAlex" not in res.stdout
    assert "No legal free copy found" in res.stdout
