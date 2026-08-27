# Local SearXNG service

This optional open-source service supplies read-only public search results to
the assistant. Docker publishes it only on `127.0.0.1:8888`; the assistant
rejects hostnames, LAN addresses, redirects, and other paths.

SearXNG is a separate service licensed under AGPL-3.0-or-later. Its source and
license are available at <https://github.com/searxng/searxng>. This project does
not copy SearXNG code into the assistant package.

The image is pinned to a reviewed multi-architecture manifest rather than
`latest`. Updating it requires reviewing release/configuration changes,
replacing both tag and digest, and rerunning the search boundary tests.

Before the first start, provide a random SearXNG session secret through the
local shell environment or an ignored `.env` file. The secret belongs only to
SearXNG and is never supplied to the assistant or model. Then start the service
from this directory with Docker Compose. Do not change the host-side port
binding from numeric loopback.

The service has no persistent volume, browser state, assistant memory, model
access, account cookies, or API credentials. Its configured upstream engines do
receive search queries. Stop the service to disable web search immediately.

Official installation and configuration references:

- <https://docs.searxng.org/admin/installation-docker>
- <https://docs.searxng.org/dev/search_api.html>
- <https://docs.searxng.org/admin/settings/settings_search.html>
