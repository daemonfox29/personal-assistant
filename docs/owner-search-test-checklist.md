# Owner Search Test Checklist

Run these in the native app tomorrow. They are practical acceptance checks for
the current `feature/search-service-controls` milestone; no terminal is needed.

## Before you start

- Open the normal desktop launcher and begin one ordinary saved chat.
- Leave the default search-source settings enabled unless a step says otherwise.
- For a clean comparison, start a new chat before the final unresolved-reference
  check.

## Conversational search and sources

1. Ask: `Tell me about Janis Joplin.` Then ask: `Can you give me some popular
   books on her?`

   Expected: it searches for Janis Joplin rather than generic books about women,
   gives a grounded book list, and shows readable source names without URLs.

2. In that same chat, ask: `Links to the books themselves, any Amazon links you
   could provide?`

   Expected: it searches again using the Janis Joplin topic. Any displayed URL
   must be a current search result, not a guessed Amazon address. If no verified
   Amazon result is available, it should say it cannot verify one rather than
   inventing a link.

3. Ask the same request with `include links` or `show the URLs`.

   Expected: source URLs become visible. Without that wording, responses should
   show source names only.

4. Start a new chat and ask: `Can you find books about her?`

   Expected: it asks who you mean. It must not retrieve a subject from a prior
   assistant answer, saved memory, or unrelated chat.

## Provider scope and current information

5. Ask: `Look up bipolar disorder on PubMed and summarize it.` Then ask: `Is
   lamotrigine a typical treatment for it? What does it do?`

   Expected: the first message uses PubMed only. The follow-up returns to the
   default health route rather than silently staying PubMed-only.

6. Ask: `Tell me some recent news about Iran.`

   Expected: it searches automatically, synthesizes an answer instead of merely
   listing results, and shows source names. Add `double-check the evidence` to
   request one extra review pass.

## UI and safety controls

7. While a longer answer is generating, open Settings or switch chats.

   Expected: the window remains responsive. Use Stop if needed; the partial
   answer should be marked stopped and should not be saved as a completed turn.

8. In Settings, change a search provider selection and the idle shutdown time.

   Expected: changes persist after restarting the app. An explicitly named
   provider that is disabled should produce a clear unavailable notice, not
   silently use another provider.

## What to report

For any problem, copy the prompt, assistant response/notices, whether it was a
new or existing chat, and whether a visible URL was wrong, missing, or worked.
Do not include private recovery phrases or passcodes.
