/**
 * A frame of the live view, as `newswitch/broadcasters/wire.py` sends it: one websocket
 * message is one whole frame, a 32-byte little-endian header and the detector's own values.
 */

const MAGIC = 0x3146534e; // "NSF1", read as a little-endian u32
const HEADER_BYTES = 32;

export interface LiveFrame {
  slot: number;
  sequence: number;
  width: number;
  height: number;
  /** The factor the sent image was binned by. */
  binning: number;
  /** A suggested contrast window, in the units of `pixels`. */
  low: number;
  high: number;
  /** When the detector handed the frame over, in seconds since the epoch. */
  timeS: number;
  pixels: Uint8Array | Uint16Array;
}

export function parseFrame(message: ArrayBuffer): LiveFrame {
  const view = new DataView(message);
  if (message.byteLength < HEADER_BYTES || view.getUint32(0, true) !== MAGIC) {
    throw new Error("Not a live view frame");
  }
  const bytesPerSample = view.getUint8(4);
  const width = view.getUint16(12, true);
  const height = view.getUint16(14, true);
  if (message.byteLength !== HEADER_BYTES + width * height * bytesPerSample) {
    throw new Error("A live view frame of the wrong size");
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
    pixels:
      bytesPerSample === 2
        ? new Uint16Array(message, HEADER_BYTES, width * height)
        : new Uint8Array(message, HEADER_BYTES, width * height),
  };
}

const shown = new WeakMap<LiveFrame, Uint8ClampedArray<ArrayBuffer>>();

/**
 * The frame as opaque gray RGBA bytes, stretched over its contrast window. Computed once
 * per frame, and only for frames that get drawn: a canvas and a texture of one frame share it.
 */
export function frameToRgba(frame: LiveFrame): Uint8ClampedArray<ArrayBuffer> {
  const known = shown.get(frame);
  if (known) return known;

  const { pixels, low, high } = frame;
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
