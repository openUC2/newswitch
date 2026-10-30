import { authFrame, WS_UNAUTHORIZED_CLOSE_CODE } from "@/lib/auth/authFetch";
import { clearToken } from "@/lib/auth/token";
import { FRAME_STREAM_PATH } from "@/constants";
import { useEffect, useRef, useState } from "react";
import { parseFrame, type LiveFrame } from "./frames";

/** The longer side of the image a viewer asks for by default, reached by binning. */
export const DEFAULT_MAX_SIZE = 640;
/** Asks for the image as the detector took it. */
export const FULL_SIZE = 0;

const RECONNECT_DELAY_MS = 1000;
/** A socket outlives its last listener this long: React remounting costs no reconnect. */
const LINGER_MS = 1000;

/** "live" from the first frame on; a socket that is open but gets none yet is "connecting". */
export type FrameStreamState = "connecting" | "live" | "disconnected";

interface Listener {
  onFrame: (frame: LiveFrame) => void;
  onState: (state: FrameStreamState) => void;
}

/**
 * One socket per slot and size, however many views show it: a frame is sent, and turned
 * into pixels, once per tab.
 */
class FrameConnection {
  private listeners = new Set<Listener>();
  private socket: WebSocket | null = null;
  private retry: ReturnType<typeof setTimeout> | null = null;
  private linger: ReturnType<typeof setTimeout> | null = null;
  private state: FrameStreamState = "connecting";
  private latest: LiveFrame | null = null;

  private readonly url: string;
  private readonly onIdle: () => void;

  constructor(url: string, onIdle: () => void) {
    this.url = url;
    this.onIdle = onIdle;
  }

  add(listener: Listener) {
    if (this.linger) clearTimeout(this.linger);
    this.linger = null;
    this.listeners.add(listener);
    listener.onState(this.state);
    if (this.latest) listener.onFrame(this.latest);
    if (!this.socket && !this.retry) this.connect();
  }

  remove(listener: Listener) {
    this.listeners.delete(listener);
    if (this.listeners.size > 0) return;
    this.linger = setTimeout(() => {
      this.close();
      this.onIdle();
    }, LINGER_MS);
  }

  private connect() {
    this.setState("connecting");
    const socket = new WebSocket(this.url);
    socket.binaryType = "arraybuffer";
    this.socket = socket;

    // In-band auth: a WebSocket cannot carry an Authorization header, and a
    // query-string token would land in every access log.
    socket.onopen = () => socket.send(JSON.stringify(authFrame()));
    socket.onmessage = (event: MessageEvent<ArrayBuffer>) => {
      // The backend sends the next frame only after this: it would otherwise buffer whatever
      // a slow client has not taken yet, without limit.
      socket.send("took it");
      const frame = parseFrame(event.data);
      this.latest = frame;
      this.setState("live");
      this.listeners.forEach((listener) => listener.onFrame(frame));
    };
    socket.onclose = (event) => {
      this.socket = null;
      this.setState("disconnected");
      // Not transient: retrying with the same rejected token would loop.
      if (event.code === WS_UNAUTHORIZED_CLOSE_CODE) {
        clearToken();
        return;
      }
      this.retry = setTimeout(() => {
        this.retry = null;
        this.connect();
      }, RECONNECT_DELAY_MS);
    };
  }

  private close() {
    if (this.retry) clearTimeout(this.retry);
    this.retry = null;
    if (!this.socket) return;
    this.socket.onclose = null;
    this.socket.close();
    this.socket = null;
  }

  private setState(state: FrameStreamState) {
    if (state === this.state) return;
    this.state = state;
    this.listeners.forEach((listener) => listener.onState(state));
  }
}

const connections = new Map<string, FrameConnection>();

/** Listen to a detector's frames; a new listener gets the newest frame straight away. */
export function subscribeFrames(
  slot: number,
  maxSize: number,
  listener: Listener,
): () => void {
  const url = `${FRAME_STREAM_PATH}/${slot}?max_size=${maxSize}`;
  let connection = connections.get(url);
  if (!connection) {
    connection = new FrameConnection(url, () => connections.delete(url));
    connections.set(url, connection);
  }
  const subscribed = connection;
  subscribed.add(listener);
  return () => subscribed.remove(listener);
}

/**
 * Calls `onFrame` with a detector's frames, as they come; it should only keep the frame.
 * Draw from the newest one when the screen is ready, so frames in between cost nothing.
 */
export function useFrameStream(
  slot: number,
  maxSize: number,
  onFrame: (frame: LiveFrame) => void,
): FrameStreamState {
  const [state, setState] = useState<FrameStreamState>("connecting");

  // In a ref so that an unmemoized callback does not re-open the subscription on every render.
  const onFrameRef = useRef(onFrame);
  useEffect(() => {
    onFrameRef.current = onFrame;
  }, [onFrame]);

  useEffect(
    () =>
      subscribeFrames(slot, maxSize, {
        onFrame: (frame) => onFrameRef.current(frame),
        onState: setState,
      }),
    [slot, maxSize],
  );

  return state;
}
