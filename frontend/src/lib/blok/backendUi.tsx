/**
 * The UI the backend declares, read at run time: its bloks and the assets they use.
 *
 * Nothing about the UI is built into the frontend. The backend chooses it (its `ui`
 * and `design` settings) and serves it at `/schemas/bloks` and `/schemas/assets`; the
 * frontend fetches both when it connects, and again when it reconnects, since a
 * restarted backend may serve another UI.
 */
import * as React from "react";
import { appDefinition } from "@/apps/default/app";
import { authFetch } from "@/lib/auth/authFetch";
import { useTransport } from "@/lib/arkitekt/transport/transport-context";
import type { NewswitchBlokDeclaration } from "@/lib/blok/newswitch";
import type { BlokAssetKind } from "@arkitektio/bsx/renderer/assets";

/** A blok as `/schemas/bloks` serves it. */
export type BackendBlok = NewswitchBlokDeclaration & {
  description?: string | null;
  context?: string | null;
  default?: boolean | null;
  /** The module it is drawn with besides the spec's catalogs (`newswitch`). */
  module?: string | null;
  catalogs?: readonly string[] | null;
};

/** An asset as `/schemas/assets` lists it: the file is at `/assets/<name>`. */
export type BackendAsset = {
  name: string;
  kind: BlokAssetKind;
  ref: string;
  size?: number | null;
};

export type BackendUi =
  | { status: "loading" }
  | { status: "error"; error: string }
  | {
      status: "ready";
      bloks: Record<string, BackendBlok>;
      assets: Record<string, BackendAsset>;
      /** Where `/assets/<name>` is served. */
      apiEndpoint: string;
    };

const BackendUiContext = React.createContext<BackendUi>({ status: "loading" });

const APP_KEY = appDefinition.key;

const fetchJson = async <T,>(url: string): Promise<T> => {
  const response = await authFetch(url);
  if (!response.ok) {
    throw new Error(`${url}: ${response.status} ${await response.text()}`);
  }
  return (await response.json()) as T;
};

/** Read the backend's UI, and read it again whenever the backend is reconnected to. */
export function BackendUiProvider({ children }: { children: React.ReactNode }) {
  const transport = useTransport();
  const [ui, setUi] = React.useState<BackendUi>({ status: "loading" });
  const [generation, setGeneration] = React.useState(0);

  // A reconnect may be to a restarted backend serving another UI.
  React.useEffect(() => {
    let wasConnected = false;
    return transport.subscribeToConnectionState(APP_KEY, (state) => {
      if (state.isConnected && !wasConnected) setGeneration((n) => n + 1);
      wasConnected = state.isConnected;
    });
  }, [transport]);

  React.useEffect(() => {
    let cancelled = false;
    const apiEndpoint = transport
      .getEndpoints(APP_KEY)
      .apiEndpoint.replace(/\/$/, "");
    Promise.all([
      fetchJson<{ bloks: Record<string, BackendBlok> }>(
        `${apiEndpoint}/schemas/bloks`,
      ),
      fetchJson<{ assets: BackendAsset[] }>(`${apiEndpoint}/schemas/assets`),
    ]).then(
      ([bloks, assets]) => {
        if (cancelled) return;
        setUi({
          status: "ready",
          bloks: bloks.bloks,
          assets: Object.fromEntries(
            assets.assets.map((asset) => [asset.name, asset]),
          ),
          apiEndpoint,
        });
      },
      (error: unknown) => {
        if (cancelled) return;
        setUi((current) =>
          // A refetch that fails keeps the UI already shown.
          current.status === "ready"
            ? current
            : { status: "error", error: String(error) },
        );
      },
    );
    return () => {
      cancelled = true;
    };
  }, [transport, generation]);

  return (
    <BackendUiContext.Provider value={ui}>{children}</BackendUiContext.Provider>
  );
}

export const useBackendUi = (): BackendUi => React.useContext(BackendUiContext);

/** The backend's default blok for a page (`default`, in the HTML context), if it declares one. */
export const defaultBlokOf = (
  bloks: Record<string, BackendBlok>,
): BackendBlok | undefined =>
  Object.values(bloks).find(
    (blok) => blok.default === true && (blok.context ?? "HTML") === "HTML",
  );

/** A view the bottom bar switches between: a blok keyed `view-…`, labelled by its description. */
export type BackendView = { key: string; label: string; blok: BackendBlok };

/**
 * The backend's views, in the order it declares them. A view's label is what its
 * description says before the first colon ("3D: the microscope …"), else its key.
 */
export const viewsOf = (bloks: Record<string, BackendBlok>): BackendView[] =>
  Object.values(bloks)
    .filter(
      (blok) =>
        blok.key.startsWith("view-") && (blok.context ?? "HTML") === "HTML",
    )
    .map((blok) => {
      const fromDescription = blok.description?.split(":")[0]?.trim();
      const fallback = blok.key.slice("view-".length);
      return {
        key: blok.key,
        label:
          fromDescription && fromDescription !== blok.description
            ? fromDescription
            : fallback.charAt(0).toUpperCase() + fallback.slice(1),
        blok,
      };
    });
