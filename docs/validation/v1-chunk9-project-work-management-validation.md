# AgentFirst V1 Chunk 9 Project/Work-Management Validation

## Command

```bash
PYTHONPATH=src python scripts/validate_v1_chunk9_project_work_management.py
```

## Coverage

The validation proves one coherent project scenario:
- a user-owned operational project with owner, contributor, and agent participants
- a project-attached policy
- a linked artifact with project provenance
- a project-owned commitment created by an authorized participant
- a milestone linking the commitment and artifact
- participant project bundle read allowed through authority
- outsider project bundle read denied through authority
- artifact export denied by the project-attached policy
- project, authority, policy, and event-log audit linkage

## Expected Result

The script prints JSON with `ok: true`.

Key output sections:
- `project`
- `linked_artifact`
- `project_commitment`
- `milestone`
- `authority`
- `policy`
- `audit`

## Notes

The scenario uses only local storage and fixture data. No external provider or channel is required for this validation.
