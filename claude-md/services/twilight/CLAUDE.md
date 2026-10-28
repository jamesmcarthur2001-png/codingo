# twilight (reverse proxy)
- Twilight doesn't know the shapes it passes. Bodies and responses are dict[str, JsonValue] or
  list[dict[str, JsonValue]]. Never import the models of the services it calls.
- List endpoints always take SupportsPagination(), SupportsFilters() and SupportsSort().
- Pass-through endpoints: one-line docstring, no :param:/:return:.
## Tests
- Pass-through routes (most routes, straight to evermore) get no tests.
- Routes with logic (e.g. the MongoDB parts) get tests: mock the downstream HTTP service,
  assert the forwarded request and the returned body.
