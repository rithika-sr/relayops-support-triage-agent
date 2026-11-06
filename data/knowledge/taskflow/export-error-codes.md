---
slug: export-error-codes
title: Export error codes
kind: article
visibility: public
component: exports
product_versions: 2.4, 2.5
valid_from: 2026-06-01T00:00:00Z
---
# Export error codes

## EXPORT_LIMIT

The export exceeds the row limit for your plan. Use filters to export a smaller set or use the background export.

## EXPORT_TIMEOUT

A synchronous export did not finish within 120 seconds. Retry with "Prepare in background".

## EXPORT_500

An unexpected server error stopped the export. Retry once. If it repeats, contact support with the project name, the approximate number of tasks, and the time of the failure so the team can find the request.
