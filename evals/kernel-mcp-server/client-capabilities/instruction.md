Centralize parsing of client-declared MCP capabilities and use it in the MCP Apps gate.

Create `src/lib/mcp/client-capabilities.ts` with:

- constants for the official Apps, Tasks, OAuth Client Credentials, and Enterprise Managed Authorization extension identifiers
- `isRecord(value)` for non-array objects
- `initializeClientCapabilities(body)` that accepts only a valid `initialize` request with an object capability map
- `clientDeclaresExtension(capabilities, extension)` that counts an extension only when its settings are an object
- `clientElicitationModes(capabilities)` that returns normalized `supportsFormMode` and `supportsUrlMode` booleans and rejects malformed mode settings

Update `mcp-apps-gate.ts` to use the shared parser and re-export the Apps extension constant. Preserve the existing Redis fallback behavior.

Work in `/workspace`. Run the focused Bun tests before finishing.
