# Typed Memory Repository

The Module 1 repository is a deterministic boundary over verified encrypted
connections. The model and chat interface never receive its database handle or
raw query capability. A narrow adapter may request ordinary bounded retrieval
and serialize only eligible payloads into an explicitly untrusted JSON data
envelope. Current tests use temporary databases, fixed synthetic keys, and
synthetic content only.

## Accepted data

The repository accepts frozen typed values rather than dictionaries or SQL.
Each supported record kind has a registered payload validator with bounded text
and a fixed JSON shape. UUIDs identify records, entities, aliases, and links;
names are never treated as identity.

Credential-associated content is prohibited. Validators conservatively reject
password, passphrase, token, private-key, recovery-phrase, PIN, and payment-card
terms, private-key markers, unsafe control characters, and oversized payloads.
This screening is defense in depth, not permission to send secrets to the
model or repository for classification.

## Revisions and lifecycle

Every record revision contains a canonical snapshot of the payload and its
status, sensitivity, mention policy, scope, entity association, validity, and
candidate expiry. SHA-256 content hashes and previous-hash links detect damaged
or internally inconsistent revision chains. SQLCipher still provides the
database's cryptographic page protection; the revision hash is not presented as
a substitute for authenticated encryption.

All writes use fixed parameterized SQL and explicit transactions. Callers must
supply the current optimistic row version. A stale version, invalid transition,
missing entity, duplicate link, damaged revision, or database failure rolls
back without overwriting the last committed state.

Supported lifecycle operations include correction, candidate confirmation or
rejection, archival, restoration, soft deletion, supersession with a typed
link, bounded candidate expiry, and permanent purge. Purge removes the record,
its revisions, feedback, and links while retaining only the opaque UUID,
timestamp, and reason in the deletion ledger.

## Model and privacy boundaries

- Explicit user memories enter as confirmed records.
- Model-generated memory enters only as a 30-day candidate and cannot revise,
  confirm, delete, supersede, or loosen controls on existing memory.
- Model-suggested aliases and entity links remain disabled until a reviewable
  candidate representation exists.
- An insight cannot become confirmed until it has three distinct evidence
  record links.
- Exact alias lookup returns every matching entity, capped at 32, so ambiguous
  names trigger clarification instead of silent merging.
- Repository audit events contain operation labels, opaque IDs, counts,
  outcomes, and fixed reason codes—not payloads, aliases, paths, SQL, or errors.

Permanent purge and privacy-loosening operations are low-level capabilities,
not conversational permissions. They remain unreachable from the running
assistant until the trusted interface, risk policy, and exact one-use approval
path required by the memory specification are implemented.
