# Module 2.2 Bounded Public Page Reading Specification

## Purpose

Module 2.2 lets the assistant synthesize current public information when search
titles and snippets are insufficient. It is a narrow extension of Module 2.1,
not a browser. The reader can retrieve limited inert text only from public HTTPS
URLs returned by the current correlated search request.

## Authority boundary

The model never supplies a URL. It may select one to three result numbers from
the current search, and deterministic code resolves those numbers against a
bounded request-scoped URL set. For broad current-events requests, the
coordinator automatically reads the first three available results before the
model's final-answer turn so synthesis does not depend on model tool judgment.

The reader cannot:

- open a URL not returned by the current search request;
- reuse results from another request or after one read;
- use HTTP, nonstandard ports, URL credentials, fragments, or non-public IPs;
- follow redirects, use proxies, cookies, sessions, authentication, JavaScript,
  forms, or downloads;
- access loopback, link-local, private, reserved, multicast, or other non-global
  addresses through a literal address or DNS answer;
- read PDF, media, archive, executable, or other non-text content;
- write page content to disk or treat it as executable instructions; or
- expose request URLs, page text, exception details, or model arguments in audit.

## Connection security

The URL must normalize to public HTTPS on port 443. DNS is resolved before the
connection; every returned address must be globally routable. The connection is
pinned to one validated address while TLS certificate validation and SNI remain
bound to the original hostname, closing the DNS-rebinding gap between validation
and connection. DNS waiting has a two-second caller timeout and at most four
resolver threads may exist, so a stalled resolver cannot grow without bound. The
client uses no environment proxy and rejects every status other than 200,
including redirects.

Only `text/html`, `application/xhtml+xml`, and `text/plain` are accepted.
Compressed responses are refused. At most a 512-KiB prefix is transferred from
each selected page, at most 1,200 normalized visible characters are returned per
page, and at most three pages are attempted sequentially. Script, style,
template, SVG, and noscript content is discarded. The complete tool result is
bounded to 5,500 bytes. Each page attempt has a hard caller deadline in addition
to socket timeouts, and at most four page-fetch workers may remain active, so a
slow-drip server cannot block the conversation indefinitely or create
unbounded background work.

## Prompt-injection handling

Page titles and extracted text are labeled `untrusted_public_page_text` and then
wrapped in the generic untrusted tool-result envelope. Trusted system text tells
the model that page content cannot change instructions, grant authority, request
secrets, or direct another tool call. Result URLs are citations, not navigation
instructions. The reader never acts on text found in a page.

## Orchestration

The normal broad-current-events flow is:

1. deterministic coordinator code recognizes current-news phrasing;
2. it invokes `search_public_web`, which derives the query from the current user
   message and accepts no model-authored query;
3. search returns up to five bounded results and stores only their public URLs
   under the current request correlation ID;
4. the coordinator calls `read_current_search_results` for result numbers 1–3;
5. the reader returns any successfully extracted pages and consumes the URL set;
6. the model's first generation turn synthesizes the current evidence and cites
   exact returned URLs, with further tools disabled for that turn.

Other factual searches may use snippets directly. If they are insufficient, the
model may propose one page-read call using current result numbers. Search and
page reading are each nonrepeatable within one user request, and the existing
three-step tool ceiling remains in force.

## Acceptance criteria

Module 2.2 is complete when tests and a real-app gate prove:

1. model-authored URLs never reach the reader;
2. result numbers bind only to the current correlated search;
3. private or mixed DNS answers, redirects, credentials, non-HTTPS URLs,
   unsupported types, compressed content, and unsafe ports fail closed;
4. TLS validates the original hostname while the socket uses a pinned public IP;
5. byte, text, page, timeout, result, and tool-step limits are enforced;
6. active markup is removed and remaining text is explicitly untrusted;
7. audit records action outcomes without query, URL, or page content;
8. the real application under a Spotlight-style environment searches, reads,
   synthesizes, cites, and closes cleanly for a broad current-events request; and
9. the complete local suite and pull-request platform gate pass.
