import { decompress } from "fzstd";

/**
 * A frame of the live view, as `newswitch/broadcasters/wire.py` sends it: one websocket
 * message is one whole frame, a 32-byte little-endian header and the detector's own values.
 */

const MAGIC = 0x3146534e; // "NSF1", read as a little-endian u32
const HEADER_BYTES = 32;
const COMPRESSION_NONE = 0;
const COMPRESSION_SHUFFLED_ZSTD = 1;

export interface LiveFrame {
  slot: number;
  sequence: number;
  width: number;
  height: number;
  /** The factor the sent image was binned by. */
  binning: number;
  /** A suggested contrast window, in the units of the pixels. */
  low: number;
  high: number;
  /** When the detector handed the frame over, in seconds since the epoch. */
  timeS: number;
  bytesPerSample: number;
  compression: number;
  /** The pixels as sent: read them with `framePixels`. */
  payload: Uint8Array<ArrayBuffer>;
}

/** Reads a message's header. The pixels are left as they came: see `framePixels`. */
export function parseFrame(message: ArrayBuffer): LiveFrame {
  const view = new DataView(message);
  if (message.byteLength < HEADER_BYTES || view.getUint32(0, true) !== MAGIC) {
    throw new Error("Not a live view frame");
  }
  const bytesPerSample = view.getUint8(4);
  const width = view.getUint16(12, true);
  const height = view.getUint16(14, true);
  const compression = view.getUint8(28);
  const payloadBytes = message.byteLength - HEADER_BYTES;
  if (
    compression === COMPRESSION_NONE
      ? payloadBytes !== width * height * bytesPerSample
      : compression !== COMPRESSION_SHUFFLED_ZSTD
  ) {
    throw new Error("A live view frame this viewer cannot read");
  }
  return {
    slot: view.getUint16(6, true),
    binning: view.getUint8(5),
    sequence: view.getUint32(8, true),
    width,
    height,
    low: view.getUint16(16, true),
    high: view.getUint16(18, true),
    timeS: view.getFloat64(20, true),
    bytesPerSample,
    compression,
    payload: new Uint8Array(message, HEADER_BYTES),
  };
}

/** The detector's values of a frame, decompressing it if it came compressed. */
export function framePixels(frame: LiveFrame): Uint8Array | Uint16Array {
  const { width, height, bytesPerSample, compression, payload } = frame;
  const count = width * height;
  if (compression === COMPRESSION_NONE) {
    return bytesPerSample === 2
      ? new Uint16Array(payload.buffer, payload.byteOffset, count)
      : payload;
  }
  const shuffled = decompress(payload, new Uint8Array(count * bytesPerSample));
  if (bytesPerSample === 1) return shuffled;
  // All low bytes come before all high bytes.
  const pixels = new Uint16Array(count);
  for (let i = 0; i < count; i++) {
    pixels[i] = shuffled[i] | (shuffled[count + i] << 8);
  }
  return pixels;
}

const shown = new WeakMap<LiveFrame, Uint8ClampedArray<ArrayBuffer>>();

/**
 * The frame as opaque gray RGBA bytes, stretched over its contrast window. Computed once
 * per frame, and only for frames that get drawn, so a frame the screen skips is not even
 * decompressed: a canvas and a texture of one frame share it.
 */
export function frameToRgba(frame: LiveFrame): Uint8ClampedArray<ArrayBuffer> {
  const known = shown.get(frame);
  if (known) return known;

  const { low, high } = frame;
  const pixels = framePixels(frame);
  const scale = high > low ? 255 / (high - low) : 0;
  const rgba = new Uint32Array(pixels.length);
  for (let i = 0; i < pixels.length; i++) {
    const gray =
      Math.min(255, Math.max(0, (pixels[i] - low) * scale) + 0.5) | 0;
    rgba[i] = 0xff000000 | (gray << 16) | (gray << 8) | gray;
  }
  const bytes = new Uint8ClampedArray(rgba.buffer);
  shown.set(frame, bytes);
  return bytes;
}
