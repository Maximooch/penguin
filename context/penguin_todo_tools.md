# Penguin Tooling TODO

This checklist tracks follow-up work for core tools and agent helpers uncovered during recent workspace runs and PDF reviews.

## High-Priority
- [ ] Replace ad-hoc PDF stream scraping with a robust extractor tool (e.g. pdfminer.six or PyMuPDF fallback). Ensure clean text post-processing (kerning/spacing fixes) and expose as `<pdf_extract>`.
- [ ] Refresh web search & browser tools to surface higher-quality snippets and filter noise; document rate limits + failure modes.

## Medium-Priority
- [ ] Introduce “lite” agents (read-only file preview, summarizer, search helper) that can be spawned quickly without full planning loops.
- [ ] Explore ergonomic sub-agent creation APIs so implementers can delegate (e.g. PDF summarizer, log triage) without custom wiring.

## Notes
- Coordinate PDF tool work with analytics/logging so future regressions are visible in `tui_debug.log` dumps.
- Web tooling refresh should consider OpenRouter filtering when investigating gateway behaviour.
