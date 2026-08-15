# CAJAS MCP Tool Catalog

All tools are vendor-neutral and return structured JSON first. `minimum_permission` refers to CAJAS effective permission after the MCP request reaches CAJAS API.

## Read Tools

### `cajas.list_workspaces`

Description: Lists CAJAS workspaces/orgs available to the authenticated user.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "include_archived": {"type": "boolean", "default": false}
  }
}
```

Output schema:

```json
{
  "type": "object",
  "properties": {
    "workspaces": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "org_id": {"type": "string"},
          "slug": {"type": "string"},
          "name": {"type": "string"},
          "role": {"type": "string"},
          "workspace_type": {"type": "string"},
          "status": {"type": "string"},
          "parent_workspace_id": {"type": ["string", "null"]}
        },
        "required": ["org_id", "name", "role"]
      }
    }
  },
  "required": ["workspaces"]
}
```

Read/write: read.
Minimum permission: authenticated CAJAS user.
CAJAS API dependency: org/auth membership APIs.
Preview support: not applicable.
Audit requirement: optional read audit.
Failure modes: `AUTH_REQUIRED`, `CAJAS_API_UNAVAILABLE`.

### `cajas.list_profiles`

Description: Lists CoA profiles for a workspace. Handles inherited CoA owner workspace through CAJAS API.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "org_id": {"type": "string"}
  },
  "required": ["org_id"]
}
```

Output schema:

```json
{
  "type": "object",
  "properties": {
    "coa_owner_org_id": {"type": "string"},
    "inherits_parent_coa": {"type": "boolean"},
    "profiles": {"type": "array", "items": {"type": "object"}}
  },
  "required": ["profiles"]
}
```

Read/write: read.
Minimum permission: workspace member.
CAJAS API dependency: `GET /api/coa/profiles`.
Failure modes: `ORG_NOT_FOUND`, `PERMISSION_DENIED`.

### `cajas.get_coa`

Description: Returns chart of accounts for a selected workspace/profile.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "org_id": {"type": "string"},
    "profile_id": {"type": ["string", "null"]},
    "include_usage": {"type": "boolean", "default": false},
    "query": {"type": ["string", "null"]},
    "active_only": {"type": "boolean", "default": true}
  },
  "required": ["org_id"]
}
```

Output schema:

```json
{
  "type": "object",
  "properties": {
    "accounts": {"type": "array", "items": {"type": "object"}},
    "coa_owner_org_id": {"type": "string"},
    "profile_id": {"type": ["string", "null"]}
  },
  "required": ["accounts"]
}
```

Read/write: read.
Minimum permission: workspace member.
CAJAS API dependency: `GET /api/coa/accounts`.
Failure modes: `ORG_NOT_FOUND`, `RESOURCE_NOT_FOUND`.

### `cajas.search_raw_entries`

Description: Searches RAW entries. This tool does not modify RAW status or assemble entries.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "org_id": {"type": "string"},
    "status": {"type": ["string", "null"], "enum": ["draft", "queued", "assembled", "voided", null]},
    "project": {"type": ["string", "null"]},
    "department": {"type": ["string", "null"]},
    "counterparty_id": {"type": ["string", "null"]},
    "date_from": {"type": ["string", "null"], "format": "date"},
    "date_to": {"type": ["string", "null"], "format": "date"},
    "query": {"type": ["string", "null"]},
    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
    "cursor": {"type": ["string", "null"]}
  },
  "required": ["org_id"]
}
```

Output schema:

```json
{
  "type": "object",
  "properties": {
    "raw_entries": {"type": "array", "items": {"type": "object"}},
    "next_cursor": {"type": ["string", "null"]}
  },
  "required": ["raw_entries"]
}
```

Read/write: read.
Minimum permission: workspace member.
CAJAS API dependency: `GET /api/raw-entries`.
Failure modes: `ORG_NOT_FOUND`, `INVALID_INPUT`.

### `cajas.search_transactions`

Description: Searches CAJAS transactions.

Input schema: same pagination/filter pattern as `cajas.search_raw_entries`, with transaction status filters.
Output schema: transaction list and `next_cursor`.
Read/write: read.
Minimum permission: workspace member.
CAJAS API dependency: transaction list APIs.
Failure modes: `ORG_NOT_FOUND`, `INVALID_INPUT`.

### `cajas.search_events`

Description: Searches accounting events. This tool does not confirm, void, sign, or alter events.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "org_id": {"type": "string"},
    "state": {"type": ["string", "null"], "enum": ["pending", "oriented", "confirmed", "voided", null]},
    "date_from": {"type": ["string", "null"], "format": "date"},
    "date_to": {"type": ["string", "null"], "format": "date"},
    "query": {"type": ["string", "null"]},
    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
    "cursor": {"type": ["string", "null"]}
  },
  "required": ["org_id"]
}
```

Output schema: event summaries and `next_cursor`.
Read/write: read.
Minimum permission: workspace member.
CAJAS API dependency: `GET /api/events`.
Failure modes: `ORG_NOT_FOUND`, `INVALID_INPUT`.

### `cajas.get_event`

Description: Returns an event and related lines/links available through CAJAS APIs.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "org_id": {"type": "string"},
    "event_id": {"type": "string"}
  },
  "required": ["org_id", "event_id"]
}
```

Output schema: event detail object.
Read/write: read.
Minimum permission: workspace member.
CAJAS API dependency: `GET /api/events/{event_id}` and related event detail APIs.
Failure modes: `RESOURCE_NOT_FOUND`, `PERMISSION_DENIED`.

### `cajas.get_judgment_context`

Description: Returns aggregated read-only judgment context for an event so a client does not need to assemble it through many calls.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "org_id": {"type": "string"},
    "event_id": {"type": "string"}
  },
  "required": ["org_id", "event_id"]
}
```

Output schema:

```json
{
  "type": "object",
  "properties": {
    "event": {"type": "object"},
    "raw_sources": {"type": "array", "items": {"type": "object"}},
    "criterion_groups": {"type": "array", "items": {"type": "object"}},
    "interpretations": {"type": "array", "items": {"type": "object"}},
    "standard_links": {"type": "array", "items": {"type": "object"}},
    "evidence": {"type": "array", "items": {"type": "object"}},
    "relations": {"type": "array", "items": {"type": "object"}},
    "governance": {"type": "object"},
    "permissions": {"type": "object"}
  },
  "required": ["event", "governance", "permissions"]
}
```

Read/write: read.
Minimum permission: reviewer recommended; backend may allow member read.
CAJAS API dependency: event detail, event standard links, interpretation statements, evidence, relation APIs.
Failure modes: `RESOURCE_NOT_FOUND`, `CAJAS_API_UNAVAILABLE`.

### `cajas.get_close_status`

Description: Returns CWM/close readiness status. This tool does not close a period or create adjustment entries.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "org_id": {"type": "string"},
    "period": {"type": ["string", "null"]}
  },
  "required": ["org_id"]
}
```

Output schema: CWM summary and close preview.
Read/write: read.
Minimum permission: reviewer recommended.
CAJAS API dependency: `/api/central-workflow/summary`, `/api/central-workflow/close-preview`.
Failure modes: `PERMISSION_DENIED`, `CAJAS_API_UNAVAILABLE`.

## File And Import Tools

### `cajas.inspect_raw_file`

Description: Analyzes a CSV/XLSX file and returns detected sheets, headers, rows, and possible column mappings. This tool does not write to CAJAS.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "org_id": {"type": "string"},
    "file": {
      "type": "object",
      "properties": {
        "uri": {"type": "string"},
        "mime_type": {"type": ["string", "null"]},
        "name": {"type": ["string", "null"]}
      },
      "required": ["uri"]
    }
  },
  "required": ["org_id", "file"]
}
```

Output schema:

```json
{
  "type": "object",
  "properties": {
    "file_summary": {"type": "object"},
    "sheets": {"type": "array", "items": {"type": "object"}},
    "detected_headers": {"type": "array", "items": {"type": "string"}},
    "sample_rows": {"type": "array", "items": {"type": "object"}},
    "inferred_mapping": {"type": "object"},
    "warnings": {"type": "array", "items": {"type": "string"}}
  },
  "required": ["file_summary", "detected_headers", "sample_rows"]
}
```

Read/write: read/inspect only.
Minimum permission: workspace member.
CAJAS API dependency: none for parsing; optional CoA context from `GET /api/coa/accounts`.
Preview support: this precedes preview.
Audit requirement: `MCP_FILE_INSPECTED`, without file contents.
Failure modes: `INVALID_FILE`, `FILE_TOO_LARGE`.

### `cajas.preview_raw_import`

Description: Computes how parsed rows would import into CAJAS using existing Smart Import logic. This tool does not write to CAJAS.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "org_id": {"type": "string"},
    "profile_id": {"type": ["string", "null"]},
    "headers": {"type": "array", "items": {"type": "string"}},
    "rows": {"type": "array", "items": {"type": "object"}},
    "column_mapping": {"type": "object"},
    "import_shape": {"type": ["string", "null"]},
    "voucher_rule": {"type": ["object", "null"]}
  },
  "required": ["org_id", "headers", "rows", "column_mapping"]
}
```

Output schema: normalized rows, unresolved mappings, warnings, preview token or preview hash.
Read/write: preview only.
Minimum permission: editor/reviewer or backend import permission.
CAJAS API dependency: `/api/smart-excel/preview`, `/api/import/preview`.
Audit requirement: `MCP_RAW_IMPORT_PREVIEWED`.
Failure modes: `COA_MAPPING_REQUIRED`, `IMPORT_UNRESOLVED`, `INVALID_INPUT`.

### `cajas.import_raw_file`

Description: Imports previously previewed RAW/transaction rows into CAJAS. Requires explicit user intent and a clean preview. This tool does not approve, orient, confirm, sign, or finalize events.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "org_id": {"type": "string"},
    "preview_id": {"type": ["string", "null"]},
    "headers": {"type": "array", "items": {"type": "string"}},
    "rows": {"type": "array", "items": {"type": "object"}},
    "column_mapping": {"type": "object"},
    "mode": {"type": "string", "enum": ["append", "smart_merge", "replace"]},
    "confirm_replace": {"type": "boolean", "default": false},
    "profile_id": {"type": ["string", "null"]}
  },
  "required": ["org_id", "headers", "rows", "column_mapping", "mode"]
}
```

Output schema: import batch/job result and reconciliation summary.
Read/write: write.
Minimum permission: editor/reviewer or backend import permission.
CAJAS API dependency: `/api/smart-excel/execute`, `/api/import/execute`.
Preview support: required.
Audit requirement: existing backend audit plus `MCP_RAW_IMPORT_EXECUTED`.
Failure modes: `IMPORT_PREVIEW_REQUIRED`, `IMPORT_UNRESOLVED`, `COA_MAPPING_REQUIRED`, `PERMISSION_DENIED`.

### `cajas.inspect_coa_file`

Description: Analyzes a CoA CSV/XLSX file and returns candidate account rows. This tool does not write to CAJAS.

Input schema: same file shape as `cajas.inspect_raw_file`, plus optional `profile_id`.
Output schema: detected headers, candidate accounts, duplicates, invalid rows.
Read/write: inspect only.
Minimum permission: admin.
CAJAS API dependency: optional `GET /api/coa/accounts`.
Audit requirement: `MCP_COA_FILE_INSPECTED`.
Failure modes: `INVALID_FILE`, `FILE_TOO_LARGE`, `PERMISSION_DENIED`.

### `cajas.preview_coa_import`

Description: Compares candidate CoA rows with an existing CoA profile and returns add/update/conflict/blocked operations. This tool does not write to CAJAS.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "org_id": {"type": "string"},
    "profile_id": {"type": "string"},
    "accounts": {"type": "array", "items": {"type": "object"}},
    "conflict_policy": {
      "type": "string",
      "enum": ["fail", "prefer_existing", "prefer_upload"],
      "default": "fail"
    }
  },
  "required": ["org_id", "profile_id", "accounts"]
}
```

Output schema:

```json
{
  "type": "object",
  "properties": {
    "summary": {"type": "object"},
    "operations": {"type": "array", "items": {"type": "object"}},
    "conflicts": {"type": "array", "items": {"type": "object"}},
    "blocked": {"type": "array", "items": {"type": "object"}},
    "preview_id": {"type": "string"}
  },
  "required": ["summary", "operations", "conflicts", "blocked"]
}
```

Read/write: preview only.
Minimum permission: admin.
CAJAS API dependency: new CoA dry-run service, existing CoA list/profile validation.
Audit requirement: `MCP_COA_IMPORT_PREVIEWED`.
Failure modes: `COA_CONFLICT`, `IMMUTABLE_OBJECT`, `PERMISSION_DENIED`.

### `cajas.import_coa`

Description: Applies accepted CoA import operations to an UPLOAD_ERP profile. This tool never overwrites locked L1 CAJAS standard accounts and does not hard-delete accounts.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "org_id": {"type": "string"},
    "profile_id": {"type": "string"},
    "preview_id": {"type": "string"},
    "accepted_operation_ids": {"type": "array", "items": {"type": "string"}}
  },
  "required": ["org_id", "profile_id", "preview_id", "accepted_operation_ids"]
}
```

Output schema: upload result, applied count, skipped count, audit id.
Read/write: write.
Minimum permission: admin.
CAJAS API dependency: existing CoA upload service after new preview validation.
Preview support: required.
Audit requirement: existing backend audit plus `MCP_COA_IMPORT_EXECUTED`.
Failure modes: `IMPORT_PREVIEW_REQUIRED`, `COA_CONFLICT`, `IMMUTABLE_OBJECT`.

## Assembly Tools

### `cajas.find_similar_assemblies`

Description: Finds historical CAJAS assembly patterns similar to selected RAW entries. This tool does not create an assembly or event.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "org_id": {"type": "string"},
    "raw_entry_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1}
  },
  "required": ["org_id", "raw_entry_ids"]
}
```

Output schema: similar raw groups/events with similarity signals.
Read/write: read.
Minimum permission: reviewer recommended.
CAJAS API dependency: new assembly recommendation service over raw_groups/raw_group_items/event meta.
Failure modes: `RESOURCE_NOT_FOUND`, `PERMISSION_DENIED`.

### `cajas.search_external_work_patterns`

Description: Searches external community/work-pattern sources for context enrichment. Results are untrusted and are not accounting evidence or accounting standards.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "query": {"type": "string"},
    "provider": {"type": "string", "enum": ["stack_exchange"], "default": "stack_exchange"},
    "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5}
  },
  "required": ["query"]
}
```

Output schema: normalized untrusted results with URLs and summaries.
Read/write: read external.
Minimum permission: reviewer recommended.
CAJAS API dependency: none.
Audit requirement: provider/query hash, not full content.
Failure modes: `EXTERNAL_PROVIDER_UNAVAILABLE`, `RATE_LIMITED`.

### `cajas.recommend_assembly`

Description: Analyzes RAW entries and returns non-binding assembly candidates. This tool does not create an assembly, modify RAW status, create an Event, approve accounting judgment, sign, or finalize anything.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "org_id": {"type": "string"},
    "raw_entry_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
    "include_external_context": {"type": "boolean", "default": false}
  },
  "required": ["org_id", "raw_entry_ids"]
}
```

Output schema:

```json
{
  "type": "object",
  "properties": {
    "candidates": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "candidate_id": {"type": "string"},
          "raw_entry_ids": {"type": "array", "items": {"type": "string"}},
          "score": {"type": "number"},
          "signals": {"type": "array", "items": {"type": "object"}},
          "warnings": {"type": "array", "items": {"type": "string"}},
          "explanation": {"type": "string"},
          "mutation": {"type": "boolean", "const": false}
        },
        "required": ["candidate_id", "raw_entry_ids", "score", "signals", "mutation"]
      }
    }
  },
  "required": ["candidates"]
}
```

Read/write: recommend only.
Minimum permission: reviewer recommended.
CAJAS API dependency: new recommendation service plus existing raw read APIs.
Audit requirement: `MCP_ASSEMBLY_RECOMMENDED`.
Failure modes: `ASSEMBLY_CONFLICT`, `EXTERNAL_PROVIDER_UNAVAILABLE`.

### `cajas.explain_assembly_recommendation`

Description: Explains a recommendation candidate from structured signals. This tool does not mutate CAJAS.

Input schema: `org_id`, candidate payload or `candidate_id`.
Output schema: signals, reasons, warnings, human-readable explanation.
Read/write: read/explain.
Minimum permission: reviewer recommended.
Failure modes: `RESOURCE_NOT_FOUND`, `INVALID_INPUT`.

## Criterion And Interpretation Tools

### `cajas.find_criterion_group`

Description: Searches existing CAJAS criterion groups in `standards`.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "org_id": {"type": "string"},
    "framework": {"type": ["string", "null"]},
    "code": {"type": ["string", "null"]},
    "query": {"type": ["string", "null"]},
    "level": {"type": ["string", "null"], "enum": ["L1", "L2", "L3", null]}
  },
  "required": ["org_id"]
}
```

Output schema: matching standards with level metadata and name provenance when available.
Read/write: read.
Minimum permission: workspace member.
CAJAS API dependency: `/api/standards/groups`.
Failure modes: `ORG_NOT_FOUND`.

### `cajas.resolve_standard_reference`

Description: Identifies external standard reference candidates such as IFRS 15.22-30. This tool does not store official standard text or official headings.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "org_id": {"type": "string"},
    "context": {"type": "string"},
    "frameworks": {"type": "array", "items": {"type": "string"}, "default": ["IFRS", "IAS", "ASC"]}
  },
  "required": ["org_id", "context"]
}
```

Output schema: reference candidates with `official_text_included=false`, `requires_review=true`.
Read/write: resolve only.
Minimum permission: reviewer recommended.
CAJAS API dependency: optional standards search.
Failure modes: `INVALID_INPUT`, `EXTERNAL_PROVIDER_UNAVAILABLE`.

### `cajas.propose_criterion_group`

Description: Prepares a CAJAS criterion group candidate. This tool does not create the group unless a future explicit create mode is added and authorized.

Input schema: org, reference candidate, suggested CAJAS-authored name/description.
Output schema: create candidate for `standards`.
Read/write: propose only.
Minimum permission: reviewer recommended.
CAJAS API dependency: standards search for duplicates.
Audit requirement: `MCP_CRITERION_GROUP_PROPOSED`.
Failure modes: `COA_CONFLICT`, `PERMISSION_DENIED`.

### `cajas.find_interpretations`

Description: Finds reusable interpretation templates under a criterion group.

Input schema: `org_id`, `criterion_group_id`, optional `level`.
Output schema: `standard_templates` summaries.
Read/write: read.
Minimum permission: workspace member; unapproved template visibility follows CAJAS API.
CAJAS API dependency: `/api/standards/interpretations`.
Failure modes: `RESOURCE_NOT_FOUND`.

### `cajas.propose_interpretation`

Description: Prepares an interpretation candidate under a criterion group. This tool does not approve, confirm, or attach final accounting judgment.

Input schema: org, criterion group, level, title, content, event context.
Output schema: interpretation candidate, duplicate/reuse candidates, approval requirements.
Read/write: propose only by default.
Minimum permission: reviewer recommended.
CAJAS API dependency: standards templates and interpretation statement APIs for lookup.
Audit requirement: `MCP_INTERPRETATION_PROPOSED`.
Failure modes: `PERMISSION_DENIED`, `IMMUTABLE_OBJECT`.

