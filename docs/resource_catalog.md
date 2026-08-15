# CAJAS MCP Resource Catalog

Resources are read-only context surfaces. Tools perform parameterized actions; resources expose stable context documents.

URI scheme:

```text
cajas://...
```

The MCP spec allows custom URI schemes if they follow URI rules. `cajas://` is appropriate because these resources are not literal local files or public web URLs.

## `cajas://capabilities`

Description: Static server capability and boundary document.

Schema:

```json
{
  "name": "CAJAS MCP",
  "version": "0.1.0",
  "protocol_version": "2025-11-25",
  "capabilities": {
    "raw_import": true,
    "coa_import": true,
    "assembly_recommendation": true,
    "external_context_search": true,
    "standard_reference_resolution": true,
    "event_confirmation": false,
    "approval": false,
    "signature": false,
    "immutable_history_mutation": false
  },
  "levels": {
    "L1": "EXTERNAL_STANDARD",
    "L2": "INTERNAL_POLICY",
    "L3": "TEMPORARY_OR_SUBJECTIVE"
  },
  "mutation_boundary": {
    "allowed": ["READ", "SEARCH", "INSPECT", "ANALYZE", "PREVIEW", "RECOMMEND", "PROPOSE", "PREPARE"],
    "not_exposed": ["FINAL_ACCOUNTING_APPROVAL", "SIGNATURE", "FINALIZE_ASSEMBLY", "CONFIRM_EVENT", "OVERRIDE_GOVERNANCE", "DELETE_CONFIRMED_EVENT", "MODIFY_IMMUTABLE_HISTORY"]
  }
}
```

Authorization: public or authenticated. If public, it must not include tenant data.

## `cajas://workspace/current`

Description: Current authenticated workspace context.

Schema:

```json
{
  "org_id": "string",
  "name": "string",
  "slug": "string",
  "role": "string",
  "workspace_type": "string",
  "status": "string",
  "parent_workspace_id": "string|null",
  "permissions": {}
}
```

Authorization: authenticated.

## `cajas://profiles`

Description: Current workspace CoA profiles.

Schema:

```json
{
  "org_id": "string",
  "coa_owner_org_id": "string",
  "inherits_parent_coa": true,
  "profiles": []
}
```

Authorization: workspace member.

## `cajas://profiles/{profile_id}/coa`

Description: CoA for a profile.

Schema:

```json
{
  "profile_id": "string",
  "coa_owner_org_id": "string",
  "accounts": []
}
```

Authorization: workspace member.

## `cajas://events/{event_id}`

Description: Event detail context.

Schema:

```json
{
  "event": {},
  "event_lines": [],
  "state": "pending|oriented|confirmed|voided",
  "immutable": true
}
```

Authorization: workspace member.

## `cajas://events/{event_id}/judgment-context`

Description: Aggregated event judgment context.

Schema:

```json
{
  "event": {},
  "raw_sources": [],
  "criterion_groups": [],
  "interpretations": [],
  "standard_links": [],
  "evidence": [],
  "relations": [],
  "governance": {},
  "permissions": {}
}
```

Data availability:

- Event and event lines: existing event APIs.
- RAW sources: via event metadata/source raw group/raw entry links where available.
- Criterion groups and interpretation templates: standards APIs.
- Event standard links: event standard link APIs.
- Evidence: event evidence APIs.
- Relations: existing relation/link APIs where available.
- Governance: event signatures, approval status, immutable state.

Authorization: workspace member; reviewer recommended for full context.

## `cajas://standards/{standard_id}`

Description: Criterion group context.

Schema:

```json
{
  "criterion_group": {
    "id": "string",
    "code": "string",
    "title": "string",
    "title_origin": "CAJAS_AUTHORED|USER_AUTHORED|INTERNAL_POLICY|OFFICIAL_LICENSED|UNKNOWN",
    "level": {
      "code": "L1|L2|L3",
      "meaning": "EXTERNAL_STANDARD|INTERNAL_POLICY|TEMPORARY_OR_SUBJECTIVE"
    }
  },
  "interpretations": []
}
```

Authorization: workspace member; unapproved templates follow CAJAS API visibility.

## Resource Pagination

`resources/list` and `resources/templates/list` should support opaque cursor pagination if the resource list grows. Clients must not parse cursors.

## Binary Resources

CAJAS MCP should not expose customer files as persistent resources by default. For client-provided files, use one-off resource reads or blobs during tool invocation, then normalize into tabular payloads and discard temporary copies.

