# fcrawl command reference

Every command prints its full option list with `--help`. This page covers what each command is for and the options that matter. Most commands also take `-o FILE` (save), `--json`, `--copy` (clipboard), `--pretty/--no-pretty` (plain output is automatic when piped), `--no-cache` and `--cache-only`.

Costs are given in gateway credits. Commands with no cost listed are free: they use yt-dlp or public JSON endpoints.

## scrape — a page as markdown

```bash
fcrawl scrape URL --save-temp            # save to a temp file, print `RESULT path=…`
fcrawl scrape URL --article --no-links   # article text only (not for API docs: too aggressive)
fcrawl scrape URL --raw --wait 5000      # no filtering, let JavaScript render first
fcrawl scrape URL -f links               # all links (from the markdown)
fcrawl scrape URL -i ".main" -e ".ads"   # CSS include / exclude
fcrawl scrape g:ab12cd --save-temp       # a [goto] result from `fcrawl search`
```

| Option | Meaning |
|---|---|
| `-f, --format` | `markdown` (default), `html`, `links`, `screenshot`; repeatable |
| `--save-temp` | write to `/tmp/fcrawl-saved/` (Windows: `%TEMP%\fcrawl-saved\`) and print only the path |
| `--article` / `--raw` | aggressive filtering / no filtering |
| `--no-links` | `[text](url)` → `text` |
| `--wait MS`, `--timeout S` | wait before capture; hard timeout (default 12 s) |
| `--screenshot-full` | full-page screenshot |
| `--no-jina` | never fall back to Jina Reader |

About 1 Firecrawl credit per page (PDFs are charged per page). Firecrawl goes first; Jina Reader is tried only if Firecrawl fails or returns a blocked page. Both results must pass the same check: challenge pages, HTTP errors and empty pages are failures (`status=blocked`) and are never cached.

## search — Google via Serper

```bash
fcrawl search "query"
fcrawl search "query" -l 20              # each extra page = 1 more credit
fcrawl search "query" -L zh-TW --location "Taipei, Taiwan"
fcrawl search "query" --since 2w         # or --tbs qdr:w
fcrawl search "query" --news
fcrawl search "site:github.com query"
fcrawl search "query" --urls-only
```

Chinese queries automatically get Taiwan results (`gl=tw`, `hl=zh-tw`). Gateway-only options:

- `--engine firecrawl`: Firecrawl's search instead (2 Firecrawl credits per 10 results, real URLs).
- `--single` / `--batches N`: control how many identical Serper searches are merged.
- `--resolve`: resolve every `[goto]` ticket after the search.
- `--debug`: show provider, timing and batch mode.

**Goto tickets.** Google sometimes replaces result links with signed `google.com/goto` tickets. fcrawl prints these as `[goto] <breadcrumb>` with a `→ fcrawl scrape g:xxxxxx` line. Scrape the `g:` id directly: fcrawl resolves it while scraping.

## resolve — goto ticket to real URL

```bash
fcrawl resolve g:ab12cd g:ef34gh [--wait] [--json]
```

Only needed when you want the URL without reading the page. Gateway mode only.

## reddit — public Reddit JSON

```bash
fcrawl reddit post URL_OR_ID [--sort top] [-l 0] [-d 5] [--no-comments] [--json]
fcrawl reddit search "query" [-s subreddit] [-u author] [--sort top -t month] [-l 50]
fcrawl reddit subreddit python [--sort top -t week] [--about]
fcrawl reddit user NAME [--posts-only | --comments-only] [--about]
```

`-l 0` on `post` means all top-level comments. `--after CURSOR` pages through listings. If Reddit blocks the JSON endpoints, fcrawl falls back to the Arctic Shift archive and to Google (`site:reddit.com`) for search.

## x — X / Twitter

```bash
fcrawl x search "query" [--sort top|latest|photos|videos] [-l 50]
fcrawl x tweet URL_OR_ID [--thread] [--with-replies] [--reply-limit 30]
fcrawl x article URL_OR_ID [--raw]       # long-form X articles
fcrawl x user HANDLE
fcrawl x tweets HANDLE [-l 50]
fcrawl x diagnose                        # preflight checks, structured report
```

`--provider` chooses the backend: `gateway` (default in gateway mode), `twscrape` (your own X accounts, the default otherwise), or `twitterapi` (twitterapi.io key). `x accounts add-tokens --ct0 … --auth …`, `add`, `login` and `reset` manage your own accounts in `~/.config/fcrawl/x_accounts.db`. That is direct mode only.

## yt-transcript, yt-channel, yt-search — YouTube

```bash
fcrawl yt-transcript URL [-l zh-Hant] [--list-langs]
fcrawl yt-transcript URL --cookies-from-browser chrome   # when YouTube throttles (429)
fcrawl yt-channel "@handle" [-n 50] [-s views] [-q keyword] [-t shorts] [--with-dates] [--ids-only]
fcrawl yt-search "query" [-n 20] [-s date] [--ids-only]
```

Transcript language order: `-l` choice, then the video's own language, then English, then the first available. Cookies can also be set in `~/.fcrawlrc` (`yt_cookies_from_browser`, `yt_cookies_file`) or with `FCRAWL_YT_COOKIES_*` env vars. By default fcrawl retries with cookies when YouTube blocks (`--no-cookies-on-fail` turns that off).

## dcard — Dcard (Taiwan forum)

Dcard pages sit behind Cloudflare, so fcrawl reads Dcard's own JSON API through Firecrawl.

```bash
fcrawl dcard search "query" [-f forum] [--sort relevance|latest|trending|interaction] [--since 90] [-l 0]
fcrawl dcard topic NAME [--hot]
fcrawl dcard forum ALIAS [--popular] [--info]
fcrawl dcard forums [-s keyword] [--school]
fcrawl dcard post ID_OR_URL [ID ...] [--sort oldest|newest|likes] [--replies N|auto|auto:N] [-l 0] [-o dir/]
```

Costs: search/topic 1 credit per 30 posts, forum 1 per 100 posts, a post 1 credit plus 1 per 30 comments. List commands share `--compact` (one line per post), `--min-likes N` and `--by-likes`. Every command prints `credits: N` on stderr at the end. `--sort interaction` finds the long, well-liked experience posts. `--replies auto` expands the most-liked reply threads.

## dev — Firecrawl Developer Index

```bash
fcrawl dev "error message or question"
fcrawl dev "error" -t issue -t pull_request    # types: doc, issue, pull_request, readme
fcrawl dev "retry on 429" -r owner/repo -p 3   # one repo, 3 passages per result
fcrawl dev "config" --source DOC_SOURCE_ID
```

Searches GitHub issues, merged PRs, READMEs and curated docs, and returns the matching passage. Repo filters (`--language`, `--topic`, `--license`, `--min-stars`, `--max-stars`) drop doc results. `dev` always calls Firecrawl Cloud directly, not the gateway. It works without a key at a small daily per-IP limit, and with a Firecrawl `api_key` it uses that key (2 credits per 10 results).

## map — discover a site's URLs

```bash
fcrawl map https://docs.example.com [--search api] [--limit 100] [--include-subdomains]
```

## cache

```bash
fcrawl cache stats          # files per command / provider, how many are junk
fcrawl cache clean [--yes]  # list (and with --yes, trash) junk scrape entries
fcrawl cache clear [scrape|search|…]
```

## config

`fcrawl config` prints the active configuration with keys and tokens masked.

## setup claude-code

```bash
fcrawl setup claude-code              # install / update skill + hook + settings + CLAUDE.md section
fcrawl setup claude-code --dry-run
fcrawl setup claude-code --doctor     # check an existing install, run the hook once
fcrawl setup claude-code --uninstall
```

Installs `skills/fcrawl/SKILL.md` and `hooks/fcrawl_gate.py` into `~/.claude` (or `$CLAUDE_CONFIG_DIR`). The hook blocks the built-in WebSearch/WebFetch and blocks `fcrawl` calls from an agent that has not loaded the skill. Run it again after every upgrade.

## transcribe

Local speech-to-text with SenseVoice (Alibaba FunASR). Needs the optional `asr` extra, which pulls in PyTorch, FunASR, pydub and OpenCC (several GB):

```bash
uv tool install --force "fcrawl[asr] @ git+https://github.com/Yan-Yu-Lin/fcrawl.git"
fcrawl transcribe recording.mp3 [-m sensevoice|paraformer|fun-asr-nano] [-f txt|srt|vtt|json] [--simplified]
```

With the extra installed, `yt-transcript` also falls back to local transcription for videos without subtitles (`-t` forces it, `--no-transcribe` disables it). Chinese output is Traditional unless you pass `--simplified`. Runs on Apple Silicon (MPS), CUDA or CPU.
