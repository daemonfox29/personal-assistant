# Module 2.4 — Evidence-Grounded Search Verification

## Purpose

Improve factual precision without pretending that a search engine or language
model can guarantee truth. A provider such as Google Scholar is a discovery
route, not a single evidence source: one provider may return several distinct
papers, reports, authors, journals, and publishers that can be compared.

## Default behavior

- Read up to three relevant current results when the coordinator performs a
  quality or current-information search.
- Prefer multiple distinct documents and primary or authoritative material when
  available. Do not count duplicated or syndicated reporting as independent
  corroboration merely because it has multiple URLs.
- Associate factual claims with the exact current-result URLs that support them.
  Omit or qualify details that the retrieved material does not support.
- State material disagreement, date limitations, and cases where only one
  relevant document was available.
- Treat a named search provider as a retrieval constraint, not as proof. An
  explicit Google Scholar-only request still compares multiple Scholar results.
- Preserve a bounded published-date field from search results when SearXNG
  supplies one, so the model can reason about freshness.

## Explicit second pass

Natural phrases including `double-check`, `cross-check`, `verify this`, and
`check your work`
request a second model pass only when public-search evidence was retrieved. The
first pass is retained as an unshown draft. The second pass receives the current
question, bounded current tool evidence, and draft, but no authority or new
tools. It must remove unsupported precision, compare evidence, identify
conflicts, and return the complete answer.

The UI shows a short `Double-checking the evidence…` notice before the reviewed
answer. Cancellation remains available during both passes. The reviewed answer,
not the discarded draft, is the only answer eligible for conversation history
or memory analysis.

## Deterministic citation boundary

- Search-backed final answers are buffered until citation validation completes.
- Every emitted HTTPS citation must exactly match a URL returned by the current
  correlated search or page-read tool result.
- At least one current evidence URL is required before an answer is presented as
  search-grounded.
- If validation fails, the unverified draft is not presented as a verified
  answer. A fixed notice asks the owner to retry or refine the request.
- Deterministic validation checks provenance, not semantic truth. The model is
  still responsible for claim-to-evidence reasoning, bounded by the instructions
  above.

## Security and efficiency

- Tool results remain untrusted data and cannot alter reviewer instructions.
- No arbitrary URLs, follow-up network requests, larger page limits, provider
  credentials, query text, or result content enter the audit trail.
- The normal path uses one model answer pass. Only an explicit owner phrase
  enables the full evidence-review pass and its additional latency and token
  use. If the normal answer fails only the deterministic citation gate, one
  bounded tool-free repair pass may correct its source links; a failed repair is
  rejected, and an explicit review never cascades into a third model pass.
- The verifier uses only bounded evidence from the same request and has no tool
  definitions, preventing a recursive search or browsing loop.

## Acceptance criteria

- Normal searched answers receive stronger multi-document grounding guidance
  without a second model pass.
- An explicit Scholar-only request remains one provider while up to three
  separate Scholar results are available for comparison.
- Explicit double-check wording produces exactly one additional model pass and
  exposes only the reviewed answer.
- Unknown or missing citations fail closed with a fixed notice.
- A normal draft with missing or altered citations receives at most one bounded
  repair attempt before that fixed failure.
- Cancellation during either pass excludes the incomplete turn from session and
  persistent-memory promotion.
- Existing context, tool, search, and response limits remain enforced.
