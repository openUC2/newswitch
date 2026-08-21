import { authFetch } from "@/lib/auth/authFetch";
import { useTransport } from "@/lib/rekuest/transport/transport-context";
import { useCallback, useState } from "react";
import { useCaptureImage } from "@/apps/default/hooks/actions";

interface UseCaptureAndDownloadOptions {
  /** Custom filename for the download (without extension) */
  filename?: string;
  /** Whether to auto-download after capture (default: true) */
  autoDownload?: boolean;
}

interface UseCaptureAndDownloadReturn {
  /** Trigger capture and optional download */
  capture: () => Promise<string | null>;
  /** Download a specific file path */
  downloadFile: (filePath: string) => Promise<void>;
  /** Whether capture is in progress */
  isCapturing: boolean;
  /** Whether download is in progress */
  isDownloading: boolean;
  /** Whether the action is locked */
  isLocked: boolean;
  /** Last captured file path */
  lastCapture: string | null;
  /** Any error that occurred */
  error: Error | null;
}

export function useCaptureAndDownload(
  options: UseCaptureAndDownloadOptions = {},
): UseCaptureAndDownloadReturn {
  const { autoDownload = true } = options;

  const { apiEndpoint } = useTransport();
  const {
    call: captureImage,
    isLoading: isCapturing,
    isLocked,
  } = useCaptureImage();

  const [isDownloading, setIsDownloading] = useState(false);
  const [lastCapture, setLastCapture] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const downloadFile = useCallback(
    async (filePath: string) => {
      setIsDownloading(true);
      setError(null);

      try {
        const baseUrl = apiEndpoint.replace(/\/$/, "");
        const url = `${baseUrl}/files/${encodeURIComponent(filePath)}`;

        const response = await authFetch(url);

        if (!response.ok) {
          throw new Error(`Failed to download file: ${response.statusText}`);
        }

        const blob = await response.blob();

        // Extract filename from path or use provided one
        const fileName = filePath.split("/").pop() || "capture.png";

        // Create download link
        const downloadUrl = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = downloadUrl;
        link.download = fileName;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);

        // Cleanup
        URL.revokeObjectURL(downloadUrl);
      } catch (err) {
        const error = err instanceof Error ? err : new Error("Download failed");
        setError(error);
        console.error("[useCaptureAndDownload] Download error:", error);
      } finally {
        setIsDownloading(false);
      }
    },
    [apiEndpoint],
  );

  const capture = useCallback(async (): Promise<string | null> => {
    setError(null);

    try {
      // `capture_image` returns one Frame per active detector. A Frame's `id` IS the
      // file handle path served by `GET /files/{file_path}` (see ImagePlane, which
      // renders `/files/${image.id}`), so the download path is the frame's id.
      console.log("[useCaptureAndDownload] Starting capture...");
      const frames = await captureImage({});
      console.log("[useCaptureAndDownload] Capture returned frames:", frames);
      const filePath = frames.return0[0]?.id ?? null;

      if (filePath) {
        setLastCapture(filePath);

        if (autoDownload) {
          await downloadFile(filePath);
        }

        return filePath;
      }

      return null;
    } catch (err) {
      const error = err instanceof Error ? err : new Error("Capture failed");
      setError(error);
      console.error("[useCaptureAndDownload] Capture error:", error);
      return null;
    }
  }, [captureImage, autoDownload, downloadFile]);

  return {
    capture,
    downloadFile,
    isCapturing,
    isDownloading,
    isLocked,
    lastCapture,
    error,
  };
}
