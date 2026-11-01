# twilight (reverse proxy)
- Twilight doesn't know the shapes it passes. Bodies and responses are dict[str, JsonValue] or
  list[dict[str, JsonValue]]. Never import the models of the services it calls.
- List endpoints always take SupportsPagination(), SupportsFilters() and SupportsSort().
- Pass-through endpoints: one-line docstring, no :param:/:return:.
## Tests
- No tests in twilight, for any route. Don't add a tests/ folder, test-plan rows or coverage commands for it.
