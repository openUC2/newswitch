import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearToken } from "@/lib/auth/token";
import { subscribeFrames } from "./frameStream";

vi.mock("@/lib/auth/token", async (original) => ({
  ...(await original<typeof import("@/lib/auth/token")>()),
  clearToken: vi.fn(),
}));

class FakeSocket {
  static instances: FakeSocket[] = [];
  binaryType = "";
  sent: string[] = [];
  closed = false;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: ArrayBuffer }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  url: string;
  constructor(url: string) {
    this.url = url;
    FakeSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.closed = true;
  }
}

function frame(sequence: number) {
  const buffer = new ArrayBuffer(32 + 2);
  const view = new DataView(buffer);
  new Uint8Array(buffer).set([0x4e, 0x53, 0x46, 0x31]);
  view.setUint8(4, 2);
  view.setUint32(8, sequence, true);
  view.setUint16(12, 1, true);
  view.setUint16(14, 1, true);
  return { data: buffer };
}

const listener = () => ({ onFrame: vi.fn(), onState: vi.fn() });

describe("subscribeFrames", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeSocket);
  });

  afterEach(() => {
    vi.runAllTimers();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("authenticates in the first message, not in the URL", () => {
    const stop = subscribeFrames(1, 640, listener());
    const socket = FakeSocket.instances[0];
    socket.onopen?.();
    expect(socket.url).toContain("/stream/frames/1?max_size=640");
    expect(socket.url).not.toContain("token");
    expect(socket.sent).toHaveLength(1);
    stop();
  });

  it("acknowledges every frame, or the backend sends no next one", () => {
    const stop = subscribeFrames(7, 640, listener());
    const socket = FakeSocket.instances[0];
    socket.onmessage?.(frame(1));
    socket.onmessage?.(frame(2));
    expect(socket.sent).toHaveLength(2);
    stop();
  });

  it("shares one socket between the views of a slot and size", () => {
    const stops = [
      subscribeFrames(2, 640, listener()),
      subscribeFrames(2, 640, listener()),
    ];
    expect(FakeSocket.instances).toHaveLength(1);
    const other = subscribeFrames(2, 0, listener());
    expect(FakeSocket.instances).toHaveLength(2);
    [...stops, other].forEach((stop) => stop());
  });

  it("hands a new view the newest frame straight away", () => {
    const first = listener();
    const stop = subscribeFrames(3, 640, first);
    FakeSocket.instances[0].onmessage?.(frame(5));
    expect(first.onFrame).toHaveBeenCalledOnce();
    expect(first.onState).toHaveBeenLastCalledWith("live");

    const late = listener();
    const stopLate = subscribeFrames(3, 640, late);
    expect(late.onFrame.mock.calls[0][0].sequence).toBe(5);
    stop();
    stopLate();
  });

  it("survives a remount, and closes once nobody came back", () => {
    subscribeFrames(4, 640, listener())();
    const stop = subscribeFrames(4, 640, listener());
    vi.advanceTimersByTime(5000);
    expect(FakeSocket.instances).toHaveLength(1);
    expect(FakeSocket.instances[0].closed).toBe(false);

    stop();
    vi.advanceTimersByTime(5000);
    expect(FakeSocket.instances[0].closed).toBe(true);
    expect(FakeSocket.instances).toHaveLength(1);
  });

  it("reconnects when the socket is lost, also before the microscope started", () => {
    const view = listener();
    const stop = subscribeFrames(5, 640, view);
    FakeSocket.instances[0].onclose?.({ code: 1013 });
    expect(view.onState).toHaveBeenLastCalledWith("disconnected");
    vi.advanceTimersByTime(1000);
    expect(FakeSocket.instances).toHaveLength(2);
    expect(view.onState).toHaveBeenLastCalledWith("connecting");
    stop();
  });

  it("gives up on a rejected token instead of looping", () => {
    const stop = subscribeFrames(6, 640, listener());
    FakeSocket.instances[0].onclose?.({ code: 1008 });
    vi.advanceTimersByTime(5000);
    expect(FakeSocket.instances).toHaveLength(1);
    expect(clearToken).toHaveBeenCalled();
    stop();
  });
});
