<!--
Update existing module cards in place without creating duplicate status tables; write "TBD" for unknown fields and "none" for missing links.
Use heading ### <MODULE>-R<N> <Title>; rounds, baseline receipts, TDD, and verification/review attempts are tracked by the workflow engine, and state history lives in Git.
Agent review_passed is separate from human acceptance/delivery; check [x] only after confirmed terminal delivery, never alongside a non-terminal status.
When Status is "Review Passed, Pending Human Acceptance" / "Accepted" / "Completed" / "Delivered" or [x] is checked, the engine automatically closes unstarted local drafts for the same task.
-->

### <MODULE>-R<N> <Title>

- [ ] Subtask completed (check only after human acceptance/delivery)
- Status: Pending
- Source: <PRD version/section, local requirement/issue, or design node link>
- Scope & Non-goals: <in-scope deliverables; explicit exclusions>
- Acceptance: <core success/error/edge scenarios and key performance/security constraints>
- Dependencies & Pending: <upstream dependencies or blocking open questions + resume condition; "none" if clear>
- Related Change / Human Confirmation: <`docs/development/changes/<task-id>/` link or human acceptance/delivery note; omit if not started>
