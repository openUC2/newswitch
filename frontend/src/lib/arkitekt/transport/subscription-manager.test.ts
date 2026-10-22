import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TransportSubscriptionManager } from "./subscription-manager";
import type { FromAgentMessage } from "./types";

class FakeSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static instances: FakeSocket[] = [];
  readyState = FakeSocket.CONNECTING;
  sent: unknown[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;

  url: string;

  constructor(url: string) {
    this.url = url;
    FakeSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(JSON.parse(data));
  }

  close() {}

  open() {
    this.readyState = FakeSocket.OPEN;
    this.onopen?.();
  }

  receive(frame: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }

  drop() {
    this.readyState = 3;
    this.onclose?.({ code: 1006 });
  }
}

const init = (pos: number, resync = false) => ({
  type: "INIT",
  tasks: { count: 0, tasks: {} },
  states: { states: {} },
  locks: { count: 0, locks: {} },
  journal: { session_id: "s1", pos, global_rev: 0, resync, states: {} },
});

describe("TransportSubscriptionManager journal", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  const connect = () => {
    const received: FromAgentMessage[] = [];
    const manager = new TransportSubscriptionManager({
      getEndpoints: () => ({ wsUrl: "ws://test/ws" }),
      getSubscriptionInit: () => ({ type: "INIT", action_keys: ["a"] }),
      reconnect: {
        maxAttempts: 3,
        initialDelay: 10,
        maxDelay: 10,
        backoffMultiplier: 1,
      },
      pingInterval: 100_000,
    });
    manager.subscribeToMessages({
      appKey: "default",
      listener: (message) => received.push(message),
    });
    return { manager, received };
  };

  it("opts in, and resumes after the last frame applied on reconnect", () => {
    const { received } = connect();
    const first = FakeSocket.instances[0];
    first.open();
    expect(first.sent[0]).toMatchObject({ journal: true, action_keys: ["a"] });
    expect(first.sent[0]).not.toHaveProperty("resume_after");

    first.receive(init(3));
    first.receive({
      type: "PROGRESS",
      task: "t",
      pos: 4,
      journal_session: "s1",
    });
    first.drop();
    vi.advanceTimersByTime(20);

    const second = FakeSocket.instances[1];
    second.open();
    expect(second.sent[0]).toMatchObject({
      journal: true,
      resume_after: 4,
      session_id: "s1",
    });

    second.receive(init(9));
    // The backlog repeats nothing already applied...
    second.receive({
      type: "PROGRESS",
      task: "t",
      pos: 4,
      journal_session: "s1",
    });
    second.receive({
      type: "COMPLETED",
      task: "t",
      pos: 5,
      journal_session: "s1",
    });

    expect(received.map((m) => [m.type, m.pos])).toEqual([
      ["INIT", undefined],
      ["PROGRESS", 4],
      ["INIT", undefined],
      ["COMPLETED", 5],
    ]);
    expect(received[0]).toMatchObject({ resumed: false });
    expect(received[2]).toMatchObject({ resumed: true });
  });

  it("starts over from the INIT when the server asks to resync", () => {
    const { received } = connect();
    const first = FakeSocket.instances[0];
    first.open();
    first.receive(init(3));
    first.drop();
    vi.advanceTimersByTime(20);

    const second = FakeSocket.instances[1];
    second.open();
    second.receive(init(12, true));
    // Frames before the new INIT's watermark are part of its world already.
    second.receive({
      type: "PROGRESS",
      task: "t",
      pos: 12,
      journal_session: "s1",
    });
    second.receive({
      type: "PROGRESS",
      task: "t",
      pos: 13,
      journal_session: "s1",
    });

    expect(received[1]).toMatchObject({ type: "INIT", resumed: false });
    expect(received.slice(2).map((m) => m.pos)).toEqual([13]);
  });
});
