# Direct mode: your own keys

Normally fcrawl talks to the family gateway, which holds every key (see the README). Without a `gateway_token`, fcrawl calls the services itself with keys from `~/.fcrawlrc`. A `.fcrawlrc` in the current directory takes priority over the one in your home folder.

```json
{
  "api_url": "https://api.firecrawl.dev",
  "api_key": "fc-account-one",
  "api_keys": ["fc-account-two", "fc-account-three"],
  "serper_api_key": "your-serper-key",
  "twitterapi_io_key": null,
  "jina_fallback": true,
  "cache_ttl_days": 7,
  "yt_cookies_from_browser": "chrome"
}
```

| Key | Used by | Notes |
|---|---|---|
| `api_url` | scrape, map, dcard | Firecrawl API. The default is `http://localhost:3002` (a self-hosted Firecrawl), so set it for Firecrawl Cloud. |
| `api_key`, `api_keys` | same | Firecrawl keys. Use **one per Firecrawl account**: rate limits are per account, so two keys from the same account don't help. |
| `rate_limit_per_minute`, `max_wait` | key pool | per-account scrape budget (10 on the Free plan); how long to wait when every key is busy (75 s) |
| `serper_api_key` | search, reddit search fallback | [serper.dev](https://serper.dev) |
| `twitterapi_io_key` | `x … --provider twitterapi` | optional paid X backend |
| `jina_fallback` | scrape | try Jina Reader when Firecrawl fails (default true) |
| `cache_ttl_days` | cache | 0 = never expire |
| `yt_cookies_from_browser`, `yt_cookies_file` | yt-transcript | for throttled or age-restricted videos |

Environment variables override the file: `FIRECRAWL_API_URL`, `FIRECRAWL_API_KEY`, `FIRECRAWL_API_KEYS` (comma-separated), `SERPER_API_KEY`, `TWITTERAPI_IO_KEY`, `FCRAWL_GATEWAY_TOKEN`, `FCRAWL_YT_COOKIES_FILE`, `FCRAWL_YT_COOKIES_FROM_BROWSER`.

## Key pool

All fcrawl processes on a machine share one state file (`/tmp/fcrawl-keys/state.json`, locked; it stores key hashes, not keys). Each request uses the key with the fewest requests in the last minute. A `429` puts that key on cooldown for its `Retry-After` time and the request moves to another key. When every key is cooling down, fcrawl waits up to `max_wait` seconds (`--max-wait` on scrape). Keys answering `401`/`402` are disabled. Running many scrapes in parallel is fine.

## X accounts (twscrape)

Without the gateway, `fcrawl x` uses your own logged-in X accounts:

```bash
fcrawl x accounts add-tokens --ct0 VALUE --auth VALUE --name myaccount
fcrawl x accounts            # list
fcrawl x accounts reset      # clear rate-limit locks
fcrawl x diagnose            # check X access end to end
```

Get `ct0` and `auth_token` from your browser's developer tools (Storage → Cookies → x.com) while logged in. `auth_token` is HttpOnly, so `document.cookie` can't see it. Accounts live in `~/.config/fcrawl/x_accounts.db`.

## Self-hosted Firecrawl

With `api_url` on `localhost`, fcrawl needs no key and skips the rate limit. `fcrawl dev` always calls Firecrawl Cloud: the Developer Index doesn't exist on a self-hosted instance.
