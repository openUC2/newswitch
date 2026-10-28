import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TransportSocketConnectionState } from "@/lib/arkitekt/transport/types";
import {
  BackendUiProvider,
  defaultBlokOf,
  viewsOf,
  useBackendUi,
  type BackendBlok,
} from "./backendUi";

const connection: {
  listener?: (state: TransportSocketConnectionState) => void;
} = {};
const transport = {
  getEndpoints: () => ({
    apiEndpoint: "http://backend/",
    wsUrl: "ws://backend/ws",
  }),
  subscribeToConnectionState: (
    _app: string,
    listener: (state: TransportSocketConnectionState) => void,
  ) => {
    connection.listener = listener;
    return () => undefined;
  },
};

vi.mock("@/lib/arkitekt/transport/transport-context", () => ({
  useTransport: () => transport,
}));

const { fetchMock } = vi.hoisted(() => ({ fetchMock: vi.fn() }));
vi.mock("@/lib/auth/authFetch", () => ({ authFetch: fetchMock }));

const blok = (key: string, extra: Partial<BackendBlok> = {}): BackendBlok =>
  ({
    key,
    components: [],
    dependencies: [],
    demo: {},
    ...extra,
  }) as BackendBlok;

const respond = (bloks: Record<string, BackendBlok>) => {
  fetchMock.mockImplementation(async (url: string) => {
    const body = url.endsWith("/schemas/bloks")
      ? { bloks }
      : { assets: [{ name: "design", kind: "MODEL_3D", ref: "sha256:ab" }] };
    return new Response(JSON.stringify(body), { status: 200 });
  });
};

function Show() {
  const ui = useBackendUi();
  if (ui.status !== "ready") return <p>{ui.status}</p>;
  return (
    <p>
      {Object.keys(ui.bloks).join(",")} | {Object.keys(ui.assets).join(",")} |{" "}
      {ui.apiEndpoint}
    </p>
  );
}

const connected = (isConnected: boolean) =>
  act(() =>
    connection.listener?.({
      isConnected,
      isReconnecting: false,
      isUnconnectable: false,
      reconnectAttempt: 0,
    }),
  );

describe("backend UI", () => {
  beforeEach(() => {
    fetchMock.mockReset();
  });
  afterEach(() => vi.clearAllMocks());

  it("reads the bloks and assets the backend serves", async () => {
    respond({ standard: blok("standard") });
    render(
      <BackendUiProvider>
        <Show />
      </BackendUiProvider>,
    );
    expect(screen.getByText("loading")).toBeTruthy();
    await screen.findByText("standard | design | http://backend");
  });

  it("reports a backend that cannot be read", async () => {
    fetchMock.mockResolvedValue(new Response("nope", { status: 500 }));
    render(
      <BackendUiProvider>
        <Show />
      </BackendUiProvider>,
    );
    await screen.findByText("error");
  });

  it("reads the UI again when the backend is reconnected to", async () => {
    respond({ standard: blok("standard") });
    render(
      <BackendUiProvider>
        <Show />
      </BackendUiProvider>,
    );
    await screen.findByText(/standard \|/);

    respond({ minimal: blok("minimal") });
    await connected(true);
    await waitFor(() => screen.getByText(/minimal \|/));
  });

  it("picks the default HTML blok", () => {
    expect(
      defaultBlokOf({
        jonda: blok("jonda", { default: false, context: "HTML" }),
        logo: blok("logo", { default: true, context: "LOGO" }),
        design: blok("design", { default: true, context: "HTML" }),
      })?.key,
    ).toBe("design");
    expect(defaultBlokOf({ jonda: blok("jonda") })).toBeUndefined();
  });

  it("lists the views, labelled by their description", () => {
    const views = viewsOf({
      "view-3d": blok("view-3d", { description: "3D: the microscope" }),
      jonda: blok("jonda"),
      "view-minimal": blok("view-minimal", { description: "No colon here" }),
      "view-logo": blok("view-logo", { context: "LOGO" }),
    });
    expect(views.map((view) => [view.key, view.label])).toEqual([
      ["view-3d", "3D"],
      ["view-minimal", "Minimal"],
    ]);
  });
});
