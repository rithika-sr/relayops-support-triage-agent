---
slug: howto-pagination
title: Pagination
kind: article
visibility: public
component: api
product_versions: 2.4, 2.5
valid_from: 2026-06-01T00:00:00Z
---
# Pagination

## Question

How does pagination work on the tasks endpoint?

## Answer

From 2.4 the tasks endpoint uses a cursor. Pass the next_cursor value from the previous response until it is null.

## Where

API reference
