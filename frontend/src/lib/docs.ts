// Where the user documentation lives, and the only place its address is written down.
//
// The docs are Markdown in the repository rather than a site of their own, so these are GitHub
// blob URLs. That is a deliberate trade rather than a stopgap: a page rendered by GitHub is
// readable the moment it is merged, with nothing to deploy and nothing to keep running — and a
// documentation link that 404s because a site is down is worse than the terse instruction it
// replaced (FR-008h).
//
// Pinned to `main`, not to a tag: the reader wants how the thing works now.
const DOCS_ROOT = 'https://github.com/gnust-company/A.R.MARIUS/blob/main/docs'

export const DOCS = {
  index: `${DOCS_ROOT}/README.md`,
  quickstart: `${DOCS_ROOT}/quickstart.md`,
  machines: `${DOCS_ROOT}/machines-and-daemon.md`,
  agents: `${DOCS_ROOT}/agents.md`,
  skills: `${DOCS_ROOT}/skills.md`,
} as const
