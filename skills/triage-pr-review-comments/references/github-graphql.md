# GitHub review-thread reference

Snippets for fetching, replying to, and resolving PR review threads via the
GitHub GraphQL API. Run through `gh api graphql` so auth is handled by `gh`.

## Fetch unresolved review threads for a PR

```bash
gh api graphql -f query='
query($owner:String!, $repo:String!, $pr:Int!) {
  repository(owner:$owner, name:$repo) {
    pullRequest(number:$pr) {
      reviewThreads(first:100) {
        nodes {
          id
          isResolved
          isOutdated
          path
          line
          comments(first:20) {
            nodes {
              databaseId
              author { login }
              body
              path
              line
            }
          }
        }
      }
    }
  }
}' -f owner=OWNER -f repo=REPO -F pr=PR_NUMBER
```

Keep only nodes where `isResolved == false`. The **first** comment's `author.login`
determines whether the thread is a review-bot thread (e.g. `cursor`,
`coderabbitai`) or a human thread. `id` is the thread node id used to resolve;
`databaseId` on a comment is used to reply in-thread.

## Reply to a review thread

```bash
gh api graphql -f query='
mutation($threadId:ID!, $body:String!) {
  addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$threadId, body:$body}) {
    comment { id url }
  }
}' -f threadId=THREAD_NODE_ID -f body="…reply text…"
```

## Resolve a review thread

```bash
gh api graphql -f query='
mutation($threadId:ID!) {
  resolveReviewThread(input:{threadId:$threadId}) { thread { isResolved } }
}' -f threadId=THREAD_NODE_ID
```

## Notes

- Resolve a **bot** thread only after its outcome is live: replies post
  immediately (resolve right after); valid-bug fixes are not live until pushed
  (resolve only after the push succeeds).
- Never resolve a **human** thread automatically — leave it for the reviewer.
- `gh pr comment <n> --body "…"` posts a top-level PR comment (used to re-trigger
  a review bot); the mutations above post *in-thread* replies.
