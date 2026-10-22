import type * as React from "react";
import { cn } from "@/lib/utils";

export type ImageProps = {
  src: string;
  /**
   * Accepted for API parity with orkestrator's image (which paints a blurhash
   * placeholder). Newswitch has no blurhash decoder, so it is ignored.
   */
  blurhash?: string | null;
  className?: string;
  alt?: string;
  style?: React.CSSProperties;
};

/** A lazily loaded image. */
export const Image = ({ src, style, className, alt }: ImageProps) => (
  <img
    key={src}
    src={src}
    style={style}
    alt={alt || "Image"}
    loading="lazy"
    className={cn(className)}
  />
);
