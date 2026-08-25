# Encrypted SQLite Provider Spike

## Decision

Use SQLCipher Community Edition through the exactly pinned `sqlcipher3==0.6.2`
binding as the initial encrypted SQLite provider. Keep it behind the project's
own database and key-provider interfaces so a future provider can replace it
without changing canonical record schemas or model-facing contracts.

This decision enables the Module 1 migration work. It is not permission to
store real personal data yet.

## Why this option

Standard Python SQLite includes FTS5 on the current machine but has no database
encryption codec. A pragma cannot add encryption to that build. Application-
level field encryption would leave schema and indexing concerns exposed and
would prevent efficient full-text search over protected values. SQLite SEE
provides full-database encryption but adds a commercial source and distribution
license to this small open-source project.

SQLCipher Community Edition provides full-file encryption, per-page integrity,
key derivation support, and cross-platform database compatibility within a
major SQLCipher version. The current `sqlcipher3` release publishes
self-contained CPython wheels for supported macOS, Windows, and Linux
architectures, avoiding a system SQLCipher dependency for the initial build.

Primary references:

- [SQLCipher project](https://github.com/sqlcipher/sqlcipher)
- [SQLCipher API](https://www.zetetic.net/sqlcipher/sqlcipher-api/)
- [`sqlcipher3` Python binding](https://github.com/coleifer/sqlcipher3)
- [`sqlcipher3` 0.6.2 package files](https://pypi.org/project/sqlcipher3/)
- [SQLite SEE](https://sqlite.org/see/doc/release/www/readme.wiki)

Community SQLCipher is not claimed to provide FIPS validation. A future need
for that certification requires a separate provider and security review.

## Boundary implemented

`EncryptedDatabase` requires:

- an explicit absolute database path whose immediate directory already exists;
- a safe key identifier resolved by a replaceable `DatabaseKeyProvider`;
- a fresh 32-byte key object for every connection;
- a required audit sink and UUID correlation identifier;
- SQLCipher major version 4, active cipher status, codec support, and FTS5;
- foreign keys on, trusted schema off, a bounded busy timeout, disabled extension
  loading, deterministic close, and restrictive POSIX file permissions; and
- fixed safe exceptions that never include paths, key material, SQLCipher error
  strings, or personal content.

There is no ordinary-SQLite fallback. If cipher status, codec support, required
version, or FTS5 is absent, opening fails before the caller receives a
connection.

The current Python binding exposes keying through SQLCipher's pragma interface.
The adapter uses only a validated 32-byte raw key rendered as fixed-length hex,
never a user-provided SQL string. It clears its mutable application-owned key
copy after configuration. Python, the binding, SQLCipher, and the operating
system may retain other temporary copies, so this is best-effort lifetime
reduction rather than guaranteed physical erasure.

## Synthetic verification completed

On the current Apple-silicon Mac and project virtual environment:

- `sqlcipher3` 0.6.2 loaded SQLCipher 4.12.0 Community;
- `PRAGMA cipher_status` returned active;
- codec and FTS5 compile options were present;
- a synthetic table was written and reopened with the same 256-bit key;
- the encrypted file did not contain the normal SQLite plaintext header;
- standard Python SQLite could not read the file;
- a different key was rejected;
- key objects were cleared after connection setup;
- unsafe and symbolic-link targets were refused;
- missing required audit output prevented key acquisition and file creation; and
- audit failures and database errors exposed no path or key content.

All automated tests use temporary directories and synthetic values. No runtime
database, real key, recovery passphrase, or personal record is created.

## Cross-platform evidence and remaining checks

The chosen package publishes CPython 3.11 wheels for macOS ARM64/x86-64,
Windows ARM64/x86/x86-64, and Linux ARM64/x86/x86-64. SQLCipher documents
database compatibility across platforms when the same major version and
settings are used.

Current limitations:

- macOS ARM64 is verified locally;
- Linux will be exercised by the existing Python 3.11 GitHub Actions job when
  this batched branch is eventually pushed;
- Windows must be added to a release or compatibility matrix before claiming a
  packaged Windows build is verified; and
- a real OS credential-store provider and portable recovery-passphrase flow are
  still future implementation work. Tests currently provide synthetic keys
  directly through the interface.

Any SQLCipher major-version, Python-binding, crypto-provider, compile-option, or
key-format change requires explicit migration testing and a renewed security
review. Database files are portable only with compatible cipher settings and
the correct key material.
