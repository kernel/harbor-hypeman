Add an optional `region` parameter to the `manage_browsers` MCP tool.

Requirements:

- Accept only `us-east` or `eu-west`.
- For `action: "create"`, forward `region` to `client.browsers.create`.
- For `action: "list"`, forward `region` to `client.browsers.list`.
- Do not pass `region` to unrelated actions.
- Document in the schema that the region is fixed after browser creation and that listing uses it as a filter.
- Add focused tests for create and list forwarding.

Work in `/workspace`. Run the relevant Bun tests before finishing.
