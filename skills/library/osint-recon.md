<!-- Ported from Hermes Agent skill collection. Original author: Hermes / Nous Research. -->
<!-- Licensed under the same terms as the original (MIT). -->

---
name: osint-recon
description: >
  Open-source intelligence (OSINT) person reconnaissance — deep-dive profiling
  of an individual using public data: social media, DNS, domains, apps, news,
  images, and public records. Produces a structured intelligence report.
tags:
  - osint
  - recon
  - intelligence
  - security
  - research
triggers:
  - "osint on [person]"
  - "find info about [person]"
  - "recon on [target]"
  - "who is [person]"
  - "dig up [person]"
  - "investigate [person]"
  - "deep dive on [person]"
---

# OSINT Person Reconnaissance

Systematic open-source intelligence gathering on a target individual.
Produces a structured report covering identity, digital footprint, infrastructure,
affiliations, and public records.

## Methodology

### Phase 1: Identity & Name Resolution
1. Search exact name in quotes: `"<full name>"`
2. Try spelling variations: transliterations (e.g. Abdullwahed vs Abdulwahed vs Abdulwaheed)
3. Search with known org/role: `"<name>" founder OR CEO OR owner`
4. LinkedIn-specific: `site:linkedin.com "<name>"`
5. If Arabic name, try multiple romanizations

### Phase 2: Social Media Enumeration
Search each platform systematically:
- **LinkedIn** — professional history, education, connections, experience
- **Instagram** — personal + business accounts (check for secondary accounts)
- **YouTube** — channels, subscriber counts, content themes
- **Telegram** — channels + personal + bots (use t.me/s/ preview for content)
- **Facebook** — pages, groups, posts mentioning the person
- **Twitter/X** — handle variations
- **TikTok** — presence check
- **GitHub** — code contributions, profile
- **Medium / Dev.to / Habr** — blog posts, articles

For each platform found:
- Record follower/subscriber counts
- Extract bio text verbatim
- Note content themes and posting frequency
- Look for cross-links between accounts

### Phase 3: Domain & Infrastructure Recon
## Domain Recon
```bash
# DNS records
dig <domain> A +short
dig <domain> MX +short
dig <domain> TXT +short
dig <domain> NS +short

# WHOIS
whois <domain> | grep -i 'registrar\|creation\|expir\|name server\|registrant'

# theHarvester - email/subdomain/IP/DNS enumeration
~/.hermes/hermes-agent/venv/bin/theHarvester -d <domain> -l 200
~/.hermes/hermes-agent/venv/bin/theHarvester -d <domain> -b all -l 500

# Unified toolkit
python3 ~/.hermes/scripts/osint.py domain <domain>
```

## Web Scraping (Anti-Bot)
```bash
# Firecrawl - JS rendering, anti-bot bypass, structured extraction
python3 -c "
from firecrawl import FirecrawlApp
app = FirecrawlApp()
result = app.scrape_url('https://target.com', params={'formats': ['markdown']})
print(result['markdown'])
"
```
- NS records → registrar/hosting (GoDaddy, Cloudflare, etc.)
- A records → hosting provider, shared/dedicated IP

### Phase 4: Email & Phone OSINT
- Use `theHarvester` for email/subdomain/IP enumeration: `~/.hermes/hermes-agent/venv/bin/theHarvester -d <domain> -l 200`
- Search for email patterns: `"<name>" email` or `site:<domain>`
- Check domain MX for email provider
- Phone: search country code + name
- Check for WhatsApp/Telegram presence via phone
- For actual email access (reading/sending), use Himalaya CLI (see `himalaya` skill) — it's the easiest path, just needs IMAP credentials
- Gmail MCP exists (`@gongrzhe/server-gmail-autoauth-mcp`) but requires Google Cloud project setup (OAuth credentials, API enablement) — only worth it if you need deep Gmail integration

### Phase 5: Company & Organization Intel
For each associated company:
- Registration details
- Employees on LinkedIn
- Website tech stack (Wix, WordPress, custom)
- Google Play / App Store apps
- Yandex Maps / Google Maps presence (addresses, reviews)

### Phase 6: Media & Public Appearances
- Podcasts and interviews: `"<name>" podcast OR interview OR episode`
- Conference speakers: `"<name>" speaker OR conference OR summit`
- News articles: `"<name)" news OR article OR feature`
- Guest lectures, university talks
- YouTube interviews on other channels

### Phase 7: Podcast, Interview & Media Deep-Dive
Beyond basic media mentions, extract detailed biographical intel from long-form content:
```bash
# YouTube video description (shortDescription from page JSON)
curl -sL 'https://www.youtube.com/watch?v=<VIDEO_ID>' -H 'User-Agent: Mozilla/5.0' | \
  grep -oP '"shortDescription":"[^"]*"' | head -1 | \
  python3 -c "import sys,json; s=sys.stdin.read(); print(json.loads('{'+s+'}').get('shortDescription',''))"

# YouTube channel metadata (channelMetadataRenderer)
curl -sL 'https://www.youtube.com/@<handle>' -H 'User-Agent: Mozilla/5.0' | \
  grep -oP '"channelMetadataRenderer":\{[^}]*\}' | head -1
```
Key intel from podcasts/interviews:
- Biographical details not on social media (age, backstory, criminal history, family)
- Company founding motivations
- Technical opinions and skill self-assessment
- Relationships and network connections
- Future plans and projects

### Phase 8: App & Platform Intel
Google Play apps reveal developer info, contact, and business details:
```bash
# Search for apps by developer name
python3 ~/.hermes/scripts/search.py 'site:play.google.com "<developer_name>"' 2>/dev/null

# App page contains developer contact, website, similar apps
curl -sL 'https://play.google.com/store/apps/details?id=<package_id>&hl=en' \
  -H 'User-Agent: Mozilla/5.0 (X11; Linux x86_64)' | \
  grep -i 'developer\|email\|address\|website' | head -20
```
Also check:
- Telegram bots associated with the target (`@username_bot`, `@the_*_bot`)
- Telegram channel analytics via public preview (`t.me/s/<channel>`)
- Yandex Maps reviews for businesses in CIS countries often have photos and detailed reviews — check for physical location intel
- Google Play developer account for other apps

### Phase 8b: Web Scraping with Firecrawl
For sites that block basic requests, use firecrawl for anti-bot bypass and JS rendering:
```python
from firecrawl import FirecrawlApp
app = FirecrawlApp(api_key="your-api-key")  # or use env var FIRECRAWL_API_KEY
result = app.scrape_url('https://target-site.com', params={'formats': ['markdown']})
print(result['markdown'])
```
Firecrawl handles: anti-bot bypass, JavaScript rendering, structured data extraction, screenshot capture.
Use when: basic curl/requests fails, site requires JS, need clean markdown from complex pages.

### Phase 9: Satellite & Geospatial Intel
For targets with known physical locations, download satellite imagery for site analysis.
See `satellite-osint` skill for the full satellite imagery toolkit.
```bash
# Geocode address → coordinates
python3 ~/.hermes/scripts/satellite.py coords "address here"

# Download satellite tiles at multiple zoom levels
python3 ~/.hermes/scripts/satellite.py download <lat> <lon> --output /path/to/output
```
Analyze imagery for: building layout, perimeter security, access points, vehicle presence, nearby landmarks.

### Phase 10: Image Collection
Download profile pictures from all platforms found:
```bash
# Telegram profile photo (from og:image in t.me/<username>)
curl -sL 'https://t.me/<username>' | grep -oP 'og:image[^>]*content="[^"]*"'

# YouTube profile pic (from channelMetadataRenderer)
curl -sL 'https://www.youtube.com/@<handle>' | grep -oP '"avatar":\{"thumbnails":\[\{"url":"[^"]*"'

# ICT/conference speaker photos
curl -sL '<conference_url>' -o photo.jpg
```

### Phase 11: Cross-Reference & Compile
Verify findings across multiple sources. Cross-reference:
- Names match across platforms
- Locations consistent
- Companies associated companies align
- Timeline is coherent

Store key findings in mem0 for future reference:
```python
from mem0 import MemoryClient
m = MemoryClient(api_key="your-api-key")  # or use env var MEM0_API_KEY
m.add("Key finding about target: [details]", user_id="osint-targets")
```

## Report Template

Structure the final report with these sections:
1. **Identity** — full name, nationality, age if known, profession
2. **Backstory** — notable history, career arc (from podcasts/interviews)
3. **Companies** — all ventures with addresses, descriptions, URLs
4. **Digital Footprint** — every social account with stats and bios
5. **Email & Phone** — contact info found
6. **Domains & Infrastructure** — DNS records, hosting, email providers
7. **Public Speaking & Media** — appearances, interviews, talks
8. **Images** — downloaded profile photos with paths
9. **Satellite Imagery** — if physical locations known (via satellite-osint skill)
10. **Certifications & Skills** — known credentials
11. **Key Interests** — topics they focus on

## Tools Used
- SearXNG (local at http://127.0.0.1:8888) via `~/.hermes/scripts/search.py`
- `~/.hermes/scripts/osint.py` — Unified OSINT toolkit (username, email, domain, IP, name recon)
- `~/.hermes/scripts/satellite.py` — Satellite imagery access (geocoding, tile download)
- `~/.hermes/scripts/gmail.py` — Gmail access via IMAP/SMTP (read, search, send emails)
- `dig` for DNS, `whois` for domain registration
- `sherlock` — Username scan across 400+ platforms
- `maigret` — Extended username OSINT with categories
- `holehe` — Email service existence checks
- `theHarvester` — Email, subdomain, IP, DNS enumeration (installed in hermes venv)
- `firecrawl` — Web scraping with anti-bot bypass, JS rendering, structured extraction
- `mem0` — Smart memory extraction, deduplication, 3-4x cheaper retrieval
- `nmap` — Port scanning (when available, needs sudo)
- Shodan API — Network/internet device search (API key in .env, free tier has limited credits)
- `curl` for fetching pages, downloading images
- Python for structured extraction
- See `references/toolkit-commands.md` for quick command reference
- See `references/top-100-ai-2026.md` for trending AI tools and projects to integrate

## Credential Handling

When targets reveal credentials, API keys, or tokens during OSINT:
- NEVER echo credentials back in chat responses
- Store securely in `~/.hermes/.env` with descriptive variable names
- Reference the credential by variable name, not by value
- If user pastes a credential, silently store it and confirm setup without repeating the value

## Pitfalls (Additional)

- **Script naming**: Don't name scripts `email.py` — conflicts with Python's built-in `email` module. Use `gmail.py` or similar.
- Shodan free tier: API key works but query credits may be 0. Check credits before relying on it for recon. Free accounts get 100 credits/month but may need email verification or tutorial completion first.
- Disk space: OSINT tools and models can fill disk fast. Clean caches regularly (`~/.hermes/cache/`, `/tmp/`). `npm cache clean --force` frees npm cache. Node.js projects need 600MB+ for node_modules.
- Node.js setup: Server may not have npm installed. Use nvm (`curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash`) to install Node.js without sudo.
- OSIRIS (github.com/simplifaisoul/osiris) is a production-ready open source Palantir alternative with 7K+ stars — real-time OSINT dashboard with flight tracking, CCTV, crypto tracing, conflict zones, vulnerability scanning. Use this instead of building from scratch.

## User Preferences
- Default to exhaustive depth — run ALL phases even if early results look complete. Users asking for OSINT want the full picture, not a summary of first-page results.
- Include images — download profile photos from every platform found and deliver via MEDIA: paths.
- Use execute_code for parallel searches — batch 4-6 independent SearXNG queries per call for speed.
- Report format: labeled key:value pairs and bullet lists, *italic* not **bold**, casual tone.
- When user asks for a "report", compile everything into one voice message (female voice, en-US-JennyNeural).
- Never show system noise (skill patches, tool logs) to user — keep responses clean.

## Pitfalls
- LinkedIn blocks scraping heavily — use meta tags and JSON-LD for structured data
- Instagram API requires auth — search results and bio snippets are the fallback
- YouTube video descriptions often don't parse cleanly from raw HTML — use channelMetadataRenderer for channel info, shortDescription for video descriptions
- Google Play pages are JS-heavy — use search results for app details instead
- Telegram telemetr.io analytics pages are behind Cloudflare — skip and use public preview at t.me/s/<username>
- Some domains may be suspended or parked — note the status (e.g. haad.uz was suspended)
- Arabic/Middle Eastern names have many romanizations — try all variants (Saud Abdullwahed → Abdulwahed → Abdulwaheed → Alwahed)
- SearXNG sometimes returns empty for niche queries — broaden search terms or use different angles
- Podcast/interview YouTube videos are goldmines for biographical detail — always check the NmaGap, Ozodlik Radiosi, or other local podcast channels for deep interviews
- Telegram channel public preview (t.me/s/) is accessible without auth and shows recent posts + subscriber count + profile photo
- Yandex Maps reviews for businesses in CIS countries often have photos and detailed reviews — check for physical location intel

## Batch Search Pattern

For maximum speed, use `execute_code` to batch 4-6 independent SearXNG queries per call:
```python
from hermes_tools import terminal
import subprocess, json

queries = ['query1', 'query2', 'query3', 'query4']
for q in queries:
    r = subprocess.run(
        ["python3", "~/.hermes/scripts/search.py", q, "--json"],
        capture_output=True, text=True, timeout=20
    )
    # process results...
```
