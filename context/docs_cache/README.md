# Documentation Cache

This directory stores cached documentation sections for progressive disclosure research.

## Structure

```
docs_cache/
├── python_requests/
│   ├── toc.json              # Table of contents with metadata
│   ├── user_quickstart.md    # Loaded section
│   └── api_session.md
├── react_docs/
│   └── hooks_useeffect.md
└── project_internal/
    └── architecture.md
```

## Cache Metadata

Each `toc.json` should include:
- `source_url`: Documentation base URL
- `last_updated`: ISO timestamp
- `version`: Documentation version if available
- `entries`: Array of TOC items

## Refresh Policy

- Auto-refresh if `last_updated` > 7 days
- Manual refresh when documentation version changes
- Clear cache on 404 errors or major structure changes

## DO NOT COMMIT

This cache is user-specific research artifacts. Do not commit to version control.
