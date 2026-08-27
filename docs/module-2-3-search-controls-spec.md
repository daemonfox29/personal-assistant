# Module 2.3 — Quality Search Controls and Cancellation

## Purpose

Give the owner clear control over the local web-search service while keeping
ordinary use natural: a question that needs current information may start the
service automatically. Prefer accurate, relevant, research-oriented sources,
support explicit single-provider instructions, and let the owner stop a model
response without freezing the rest of the interface.

## Owner decisions

- Quality-first is the default search policy.
- No paid API, account, or credential is required. Google Web and Google
  Scholar use the reviewed open-source SearXNG adapters and are disclosed as
  potentially rate-limited or blocked.
- The reviewed source set is Google Web, Google Scholar, OpenAlex, Crossref,
  PubMed, Semantic Scholar, arXiv, Wikipedia, Encyclopedia.com as a preferred
  reference domain, and an optional DuckDuckGo fallback that is off by default.
- Provider selection is global and persistent. At least one source must remain
  enabled.
- Natural direct phrases such as “only search Google for this,” “check Google
  Scholar search for info on…,” “use Crossref to find…,” or “look it up with
  PubMed” select exactly that enabled provider for the current request, including
  when ordinary prose continues after the provider name. Failure does not
  silently fall back to another provider.
- Without an override, trusted code routes general/current queries to Google,
  scholarly queries to at most three scholarly sources, health/science queries
  to PubMed plus Google Scholar, and explicit reference queries to Wikipedia
  plus Encyclopedia.com. A narrower enabled subset is respected.
- Search starts automatically when needed. Manual Stop means stop after the
  active search finishes; a later eligible question may start it again.
- Idle choices are 1, 2, 5, 10, 15, and 30 minutes. Changes apply immediately
  when safe and otherwise to the next idle period.
- One failed search is retried exactly once. The UI announces the retry and then
  shows a stable diagnostic code if the retry also fails.
- While a response is active, Stop generation cancels future model/tool work,
  preserves visible partial text with a Stopped notice, and excludes the
  incomplete turn from session-memory promotion and automatic persistent-memory
  analysis.

## Trust and authority boundaries

- Widgets receive only inert status and preference values. They do not receive
  subprocess runners, container handles, model adapters, audit sinks, database
  objects, or secrets.
- The model cannot install, start, stop, configure, update, or keep alive the
  search runtime. A trusted coordinator starts it only while executing the
  registered read-only search operation.
- Provider names are selected from a packaged allowlist. Model output cannot
  add a provider, URL, proxy, credential, command, engine name, or configuration
  fragment.
- The outbound query is derived only from the current user message. The only
  code-added text is a fixed `site:encyclopedia.com` restriction when the owner
  selected the reviewed Encyclopedia.com source.
- Personal-memory and personal-health wording never triggers deterministic
  public prefetch. The owner may still deliberately request an enabled provider
  in that same current message.
- Google and Scholar requests may expose the query and public network address
  to those services. The UI states this plainly. Query text, results, URLs,
  provider secrets, and command output never enter the audit trail.
- A future opt-in VPN/proxy layer is separately deferred. No proxy credential or
  bypass authority is added here.

## Search routing

The route is computed once from the current normalized user message:

1. An explicit enabled-provider phrase wins and produces one-provider mode.
2. Clear health/science language selects PubMed and Scholar when enabled.
3. Clear research language selects up to three enabled scholarly indexes.
4. Clear reference language selects the enabled reference sources.
5. Everything else selects Google Web when enabled, followed by the first
   enabled general provider if Google is disabled.

The chosen engine names are sent to SearXNG through its fixed loopback POST
request. The model never supplies them.

## Runtime controls and status

Settings shows Installed, Off, Starting, Ready, Busy, Stopping after current
search, Unavailable, or Closed. Start and Stop run outside the UI thread. Status
is bounded and does not send a search query. Stop during an active request sets
a trusted pending-stop flag; the runtime stops when the active count returns to
zero.

## Diagnostics and retry

Only fixed public codes cross the service boundary:

- `WEB-START-01`: the isolated local search runtime could not start.
- `WEB-CONNECT-01`: the loopback service could not be reached.
- `WEB-RESPONSE-01`: the service returned an invalid or rejected response.
- `WEB-PROVIDER-01`: the requested provider is unavailable or disabled.

Codes may be paired with fixed plain-language guidance. They never contain an
exception string, command output, URL, query, filesystem path, IP address, or
credential. Each execution attempt remains content-free audited.

## Acceptance criteria

- Existing preferences migrate without losing appearance, model, or backup
  settings; malformed or unknown provider data fails closed.
- The default quality profile selects Google Web for general/current questions
  and the reviewed scholarly routes for clear research requests.
- Explicit Google and Google Scholar requests select exactly one engine and are
  denied if that source is disabled.
- At most three sources are selected automatically and at most one retry occurs.
- Provider and idle settings persist, apply safely, and never modify the checked-
  in SearXNG configuration with user or model text.
- Manual Start, finish-then-Stop, idle rescheduling, automatic restart, and
  status transitions have deterministic tests.
- Stop generation remains responsive during streaming, retains partial display
  text, stores a Stopped transcript notice, and performs no incomplete-turn
  memory promotion.
- UI navigation remains usable while generation or search work runs.
- The full automated suite and repository safety checks pass before commit.
