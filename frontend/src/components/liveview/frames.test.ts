import { describe, expect, it } from "vitest";
import { framePixels, frameToRgba, parseFrame } from "./frames";

const COMPRESSED_BY_THE_BACKEND = "KLUv/SAghQAAQGSgyCwAAAABAgCAI3OOCA==";

function message({
  sample = 2,
  width = 2,
  height = 2,
  low = 100,
  high = 200,
  values = [100, 150, 200, 300],
}) {
  const buffer = new ArrayBuffer(32 + width * height * sample);
  const view = new DataView(buffer);
  new Uint8Array(buffer).set([0x4e, 0x53, 0x46, 0x31]); // NSF1
  view.setUint8(4, sample);
  view.setUint8(5, 3);
  view.setUint16(6, 7, true);
  view.setUint32(8, 42, true);
  view.setUint16(12, width, true);
  view.setUint16(14, height, true);
  view.setUint16(16, low, true);
  view.setUint16(18, high, true);
  view.setFloat64(20, 1.5, true);
  const pixels =
    sample === 2 ? new Uint16Array(buffer, 32) : new Uint8Array(buffer, 32);
  pixels.set(values);
  return buffer;
}

describe("parseFrame", () => {
  it("reads the header the backend writes, and the values untouched", () => {
    const frame = parseFrame(message({}));
    expect(frame).toMatchObject({
      slot: 7,
      binning: 3,
      sequence: 42,
      width: 2,
      height: 2,
      low: 100,
      high: 200,
      timeS: 1.5,
    });
    const pixels = framePixels(frame);
    expect(Array.from(pixels)).toEqual([100, 150, 200, 300]);
    expect(pixels).toBeInstanceOf(Uint16Array);
  });

  it("reads uint8 frames as uint8", () => {
    const frame = parseFrame(
      message({ sample: 1, low: 0, high: 255, values: [1, 2, 3, 4] }),
    );
    const pixels = framePixels(frame);
    expect(pixels).toBeInstanceOf(Uint8Array);
    expect(Array.from(pixels)).toEqual([1, 2, 3, 4]);
  });

  it("decompresses what the backend compressed, value for value", () => {
    // wire.py's output for a 4x4 uint16 frame of 100, 160, 200, 300 repeated: byte-shuffled, zstd.
    const compressed = Uint8Array.from(atob(COMPRESSED_BY_THE_BACKEND), (c) =>
      c.charCodeAt(0),
    );
    const buffer = message({ width: 0, height: 0, values: [] });
    const whole = new Uint8Array(32 + compressed.length);
    whole.set(new Uint8Array(buffer));
    whole.set(compressed, 32);
    const view = new DataView(whole.buffer);
    view.setUint16(12, 4, true);
    view.setUint16(14, 4, true);
    view.setUint8(28, 1);

    const frame = parseFrame(whole.buffer);
    expect(Array.from(framePixels(frame))).toEqual(
      Array.from({ length: 16 }, (_, i) => [100, 160, 200, 300][i % 4]),
    );
    expect(Array.from(frameToRgba(frame).slice(4, 8))).toEqual([
      153, 153, 153, 255,
    ]);
  });

  it("refuses a compression it does not know", () => {
    const buffer = message({});
    new DataView(buffer).setUint8(28, 9);
    expect(() => parseFrame(buffer)).toThrow();
  });

  it("refuses what is not a frame", () => {
    expect(() => parseFrame(new ArrayBuffer(8))).toThrow();
    expect(() => parseFrame(new ArrayBuffer(64))).toThrow();
    expect(() => parseFrame(message({}).slice(0, 34))).toThrow();
  });
});

describe("frameToRgba", () => {
  const gray = (rgba: Uint8ClampedArray) =>
    Array.from(rgba).filter((_, index) => index % 4 === 0);

  it("stretches the contrast window over the display's range", () => {
    const frame = parseFrame(message({ values: [100, 160, 200, 300] }));
    expect(gray(frameToRgba(frame))).toEqual([0, 153, 255, 255]);
  });

  it("is opaque gray", () => {
    const frame = parseFrame(message({ values: [100, 160, 200, 300] }));
    expect(Array.from(frameToRgba(frame).slice(4, 8))).toEqual([
      153, 153, 153, 255,
    ]);
  });

  it("shows an image without contrast as black, not as noise", () => {
    const frame = parseFrame(
      message({ low: 5, high: 5, values: [5, 5, 5, 5] }),
    );
    expect(gray(frameToRgba(frame))).toEqual([0, 0, 0, 0]);
  });

  it("converts a frame once, however many views draw it", () => {
    const frame = parseFrame(message({}));
    expect(frameToRgba(frame)).toBe(frameToRgba(frame));
  });
});
