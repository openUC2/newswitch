import { authFetch } from "@/lib/auth/authFetch";
import { useIOState } from "@/apps/default/hooks/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useTransport } from "@/lib/rekuest/transport/transport-context";
import { Download, ImageIcon, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

export function LatestImage() {
  const { data: ioState, loading: stateLoading } = useIOState({
    subscribe: true,
  });
  const { apiEndpoint } = useTransport();

  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [isLoadingImage, setIsLoadingImage] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastFile, setLastFile] = useState<string | null>(null);
  const imageUrlRef = useRef<string | null>(null);

  // Fetch image when last_saved_file changes
  useEffect(() => {
    const filePath = ioState?.last_saved_file;

    if (!filePath || filePath === lastFile) return;

    setLastFile(filePath);
    setIsLoadingImage(true);
    setError(null);

    const fetchImage = async () => {
      try {
        // Construct the URL to fetch the image from backend
        const baseUrl = apiEndpoint.replace(/\/$/, "");
        const url = `${baseUrl}/files/${encodeURIComponent(filePath)}`;

        const response = await authFetch(url);

        if (!response.ok) {
          throw new Error(`Failed to fetch image: ${response.status}`);
        }

        const blob = await response.blob();

        // Revoke old URL to prevent memory leaks
        if (imageUrlRef.current) {
          URL.revokeObjectURL(imageUrlRef.current);
        }

        const newUrl = URL.createObjectURL(blob);
        imageUrlRef.current = newUrl;
        setImageUrl(newUrl);
        setError(null);
      } catch (err) {
        console.error("[LatestImage] Error fetching image:", err);
        setError(err instanceof Error ? err.message : "Failed to load image");
      } finally {
        setIsLoadingImage(false);
      }
    };

    fetchImage();
  }, [ioState?.last_saved_file, lastFile, apiEndpoint]);

  // Cleanup URL on unmount
  useEffect(() => {
    return () => {
      if (imageUrlRef.current) {
        URL.revokeObjectURL(imageUrlRef.current);
      }
    };
  }, []);

  const handleDownload = () => {
    if (!imageUrl || !lastFile) return;

    const link = document.createElement("a");
    link.href = imageUrl;
    link.download = lastFile.split("/").pop() || "image.png";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleRefresh = () => {
    if (lastFile) {
      setLastFile(null); // Force refetch
    }
  };

  return (
    <Card className="w-full">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <ImageIcon className="h-5 w-5" />
              Latest Image
            </CardTitle>
            <CardDescription>Most recently saved image</CardDescription>
          </div>
          <div className="flex items-center gap-2">
            {stateLoading && <Badge variant="outline">Syncing...</Badge>}
            {isLoadingImage && <Badge variant="secondary">Loading...</Badge>}
            {imageUrl && (
              <>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={handleRefresh}
                  title="Refresh image"
                >
                  <RefreshCw className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={handleDownload}
                  title="Download image"
                >
                  <Download className="h-4 w-4" />
                </Button>
              </>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {/* File path display */}
          {lastFile && (
            <div className="text-xs text-muted-foreground font-mono truncate">
              {lastFile}
            </div>
          )}

          {/* Image display area */}
          <div className="relative aspect-video bg-muted rounded-lg overflow-hidden flex items-center justify-center">
            {isLoadingImage && <Skeleton className="absolute inset-0" />}

            {error && !isLoadingImage && (
              <div className="text-center p-4">
                <ImageIcon className="h-8 w-8 mx-auto text-muted-foreground mb-2" />
                <p className="text-sm text-muted-foreground">{error}</p>
              </div>
            )}

            {!imageUrl && !isLoadingImage && !error && (
              <div className="text-center p-4">
                <ImageIcon className="h-8 w-8 mx-auto text-muted-foreground mb-2" />
                <p className="text-sm text-muted-foreground">
                  No image captured yet
                </p>
              </div>
            )}

            {imageUrl && !isLoadingImage && (
              <img
                src={imageUrl}
                alt="Latest captured image"
                className="w-full h-full object-contain"
              />
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
