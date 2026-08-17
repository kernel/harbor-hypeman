/// <reference types="bun-types" />

import { describe, expect, test } from "bun:test";
import { connectTestMcp, toolResultJSON } from "@/lib/mcp/mcp-test-fixtures";
import { registerBrowserCapabilities } from "@/lib/mcp/tools/browsers";

describe("manage_browsers region", () => {
  test("forwards region only for create and list", async () => {
    const createCalls: unknown[] = [];
    const listCalls: unknown[] = [];
    const getCalls: unknown[] = [];
    const kernelClient = {
      browsers: {
        create: async (params: unknown) => {
          createCalls.push(params);
          return { session_id: "brr_created" };
        },
        list: async (params: unknown) => {
          listCalls.push(params);
          return {
            getPaginatedItems: () => [{ session_id: "brr_eu" }],
            has_more: false,
            next_offset: null,
          };
        },
        retrieve: async (sessionId: string) => {
          getCalls.push(sessionId);
          return { session_id: sessionId };
        },
      },
    };
    const { client, close } = await connectTestMcp(
      registerBrowserCapabilities,
      kernelClient,
    );

    try {
      const created = toolResultJSON(
        await client.callTool({
          name: "manage_browsers",
          arguments: { action: "create", region: "eu-west", stealth: true },
        }),
      );
      expect(createCalls).toEqual([{ stealth: true, region: "eu-west" }]);
      expect(created.browser.session_id).toBe("brr_created");

      const listed = toolResultJSON(
        await client.callTool({
          name: "manage_browsers",
          arguments: { action: "list", region: "eu-west", limit: 5 },
        }),
      );
      expect(listCalls).toEqual([{ region: "eu-west", limit: 5 }]);
      expect(listed.items).toEqual([{ session_id: "brr_eu" }]);

      await client.callTool({
        name: "manage_browsers",
        arguments: {
          action: "get",
          session_id: "brr_created",
          region: "eu-west",
        },
      });
      expect(getCalls).toEqual(["brr_created"]);
    } finally {
      await close();
    }
  });

  test("rejects unknown regions", async () => {
    const { client, close } = await connectTestMcp(
      registerBrowserCapabilities,
      { browsers: {} },
    );
    try {
      const result = await client.callTool({
        name: "manage_browsers",
        arguments: { action: "list", region: "moon-1" },
      });
      expect(result.isError).toBe(true);
    } finally {
      await close();
    }
  });
});
