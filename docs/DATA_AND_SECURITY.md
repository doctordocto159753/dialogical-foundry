# Data and security

Dialogical Foundry v1 is designed for one trusted user on a local machine.

## Stored data

- `foundry.sqlite3`: run metadata, events, settings, node overrides, encrypted keys.
- `.master-key`: Fernet key used to encrypt secrets in SQLite.
- `runs/<id>/input`: intake manifest and uploaded source files.
- `runs/<id>/state.json`: resumable state without secret values.
- `runs/<id>/outputs`: generated planning artifacts.

Back up the complete data directory to preserve both encrypted keys and the master key. Backing up only SQLite makes stored secrets undecryptable. Deleting the complete directory resets all local state.

## Secret lifecycle

Secrets enter through a write-only API, are encrypted before SQLite storage, and are resolved only immediately before the matching provider call. Key list responses contain only id, provider, label, fingerprint, and timestamps. State, events, artifacts, pipeline JSON, and ordinary logs contain only references.

Deep Research checkpoints contain the remote operation ID and the provider's raw research report after completion, but never the API key. Treat `data/runs/<id>/state.json` as user content: it can include submitted context, cited source text, and model output. Per-node Base URLs are also persisted in SQLite and run snapshots; credentials in URLs are rejected.

Fernet protects secrets if the database alone is copied; it does not protect against an attacker who can read both the database and local master-key file. Use filesystem encryption and normal OS account controls for stronger protection.

## Untrusted inputs

Uploads and public repository text are untrusted content, not instructions. Foundry applies fixed limits, generated storage paths, type allowlists, canonical GitHub URL validation, fixed outbound hosts, no redirect following, and prompt delimiters. Model prompt-injection risk cannot be eliminated; inspect important artifacts before handing them to a coding agent.

## Network exposure

The default bind address is localhost. Do not bind v1 directly to a public interface: it has no authentication, tenancy, CSRF scheme for hostile sites, or production vault integration. A server deployment requires the evolution steps described in `ARCHITECTURE.md`.
