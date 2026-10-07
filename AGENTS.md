# Working on a restoration

- Read README.md, docs/workflow.md and docs/lessons-from-lecture-1.md first.
- Keep sources, generated guides, weights and private state outside Git. Respect
  media and dependency terms; the code license does not clear a film upload.
- Never modify the immutable source or a previously approved reused master.
- Half-open frame ranges and actual native timestamps are authoritative.
- Do not turn render completion, technical equality or a sparse sample review
  into a claim of full visual acceptance. Record exact inspected scope and hash.
- One GPU worker, one writer per state scope; independent reviewers own disjoint
  frame intervals. Bind reviews to artifacts and preserve rejected decisions.
- Start one explicit batch per session unless the operator requests more.
  "About daily" is a working pace, not authorization to create a scheduled job.
- Before changing a live pipeline, work in a separate checkout and run relevant
  regression checks. Keep inference settings and model pins unchanged unless
  a controlled comparison supports a deliberate update.
- Rerender the smallest affected dependency scope. Document masks, dissolve
  handles, guide changes and any necessary invalidation of neighboring batches.
- No deletion without path containment, obsolete-media and replacement proofs.
- Never hardcode review PASS records for unseen output or suppress a quality hold.
- Record elapsed preparation, propagation, correction, encode and QA separately.
