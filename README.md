# CAJAS MCP

Vendor-neutral MCP adapter for CAJAS accounting workflows.

This implementation is a thin adapter over the authenticated CAJAS API:

```text
MCP Client
  -> CAJAS MCP Server
  -> CAJAS FastAPI
  -> backend/supabase_admin.py
  -> Supabase
```

## Design Documents

- [Protocol Contract](docs/protocol_contract.md)
- [Deployment and Repository Design](docs/deployment_and_repository.md)
- [Tool Catalog](docs/tool_catalog.md)
- [Resource Catalog](docs/resource_catalog.md)
- [Release Checklist](docs/release_checklist.md)

## Implemented In This Phase

- Streamable HTTP MCP skeleton at `/mcp`.
- Local stdio entrypoint.
- `/health`, `/ready`, `/version`.
- CAJAS API HTTP client with bearer forwarding, `x-org-id`, request IDs, read retries, and error normalization.
- Read-only tools:
  - `cajas.list_workspaces`
  - `cajas.search_raw_entries`
  - `cajas.search_events`
  - `cajas.get_event`
- Resource:
  - `cajas://capabilities`
- Assembly Recommendation PoC:
  - deterministic weighted signals;
  - pairwise threshold grouping;
  - optional Stack Exchange external context;
  - non-binding output with `mutation=false`.

## Assembly Recommendation Boundary

CAJAS MCP can analyze RAW accounting entries and suggest explainable Assembly candidates using transaction structure and optional external operational context.

Recommendations are non-binding. They do not determine accounting treatment and never finalize accounting judgment.

## Planned

- RAW CSV/XLSX import.
- CoA import preview/import.
- Criterion reference resolver.
- Interpretation proposal.
- OAuth protected-resource production auth.

## Non-Goals

- No direct Supabase access from MCP.
- No CAJAS domain model redefinition.
- No GPT/Claude/vendor-specific tool branches.
- No approval, signature, finalization, governance override, or immutable history mutation tools.
- No IFRS/GAAP full-text catalog or automatic official heading replication.
- No trusted execution of external community/web content.

## Local Development

```text
pip install -e .
set CAJAS_API_BASE_URL=https://your-cajas-api.example
uvicorn cajas_mcp.app:app --host 127.0.0.1 --port 8000
```

Connect an MCP client to:

```text
http://127.0.0.1:8000/mcp
```

For stdio:

```text
set CAJAS_MCP_TRANSPORT=stdio
cajas-mcp
```
