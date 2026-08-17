/// <reference types="bun-types" />

import { describe, expect, test } from "bun:test";
import {
  clientDeclaresExtension,
  clientElicitationModes,
  initializeClientCapabilities,
  isRecord,
  MCP_APPS_EXTENSION,
  MCP_ENTERPRISE_MANAGED_AUTHORIZATION_EXTENSION,
  MCP_OAUTH_CLIENT_CREDENTIALS_EXTENSION,
  MCP_TASKS_EXTENSION,
} from "@/lib/mcp/client-capabilities";
import { initializeDeclaresMcpApps } from "@/lib/mcp/tools/mcp-apps-gate";

describe("client capability parsing", () => {
  test("extracts only object capabilities from initialize", () => {
    const capabilities = { sampling: {}, extensions: {} };
    expect(
      initializeClientCapabilities({
        method: "initialize",
        params: { capabilities },
      }),
    ).toBe(capabilities);
    expect(initializeClientCapabilities({ method: "tools/list" })).toBeNull();
    expect(
      initializeClientCapabilities({
        method: "initialize",
        params: { capabilities: [] },
      }),
    ).toBeNull();
  });

  test("requires extension settings to be objects", () => {
    expect(
      clientDeclaresExtension(
        { extensions: { [MCP_APPS_EXTENSION]: {} } },
        MCP_APPS_EXTENSION,
      ),
    ).toBe(true);
    for (const invalid of [true, "enabled", [], null]) {
      expect(
        clientDeclaresExtension(
          { extensions: { [MCP_APPS_EXTENSION]: invalid } },
          MCP_APPS_EXTENSION,
        ),
      ).toBe(false);
    }
  });

  test("normalizes form and URL elicitation modes", () => {
    expect(clientElicitationModes({ elicitation: { form: {} } })).toEqual({
      supportsFormMode: true,
      supportsUrlMode: false,
    });
    expect(clientElicitationModes({ elicitation: { url: {} } })).toEqual({
      supportsFormMode: false,
      supportsUrlMode: true,
    });
    expect(
      clientElicitationModes({ elicitation: { form: {}, url: {} } }),
    ).toEqual({ supportsFormMode: true, supportsUrlMode: true });
    expect(
      clientElicitationModes({ elicitation: { form: true, url: [] } }),
    ).toEqual({ supportsFormMode: false, supportsUrlMode: false });
  });

  test("exports the official extension identifiers", () => {
    expect(MCP_APPS_EXTENSION).toBe("io.modelcontextprotocol/ui");
    expect(MCP_TASKS_EXTENSION).toBe("io.modelcontextprotocol/tasks");
    expect(MCP_OAUTH_CLIENT_CREDENTIALS_EXTENSION).toBe(
      "io.modelcontextprotocol/oauth-client-credentials",
    );
    expect(MCP_ENTERPRISE_MANAGED_AUTHORIZATION_EXTENSION).toBe(
      "io.modelcontextprotocol/enterprise-managed-authorization",
    );
    expect(isRecord({})).toBe(true);
    expect(isRecord([])).toBe(false);
  });

  test("uses strict extension parsing in the MCP Apps initialize gate", () => {
    expect(
      initializeDeclaresMcpApps({
        method: "initialize",
        params: {
          capabilities: { extensions: { [MCP_APPS_EXTENSION]: {} } },
        },
      }),
    ).toBe(true);
    expect(
      initializeDeclaresMcpApps({
        method: "initialize",
        params: {
          capabilities: { extensions: { [MCP_APPS_EXTENSION]: true } },
        },
      }),
    ).toBe(false);
  });
});
