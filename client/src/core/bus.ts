/** WebSocket bus with a polling fallback.

The server keeps messages in PostgreSQL, so `last` is the only state that must
survive a reconnect. Redis on the server decides how quickly the socket wakes;
the browser does not care which transport delivered the envelope.
 */

import { signal, type Signal } from "./signals";

export type BusStatus = "connecting" | "live" | "polling" | "offline";

export interface BusEnvelope {
  id: number;
  channel: string;
  event: string;
  payload: Record<string, unknown>;
  create_date?: string;
}

type Handler = (message: BusEnvelope) => void;

export class BusClient {
  readonly status: Signal<BusStatus> = signal<BusStatus>("connecting");
  private socket: WebSocket | null = null;
  private last = 0;
  private stopped = false;
  private reconnectTimer: number | undefined;
  private pollTimer: number | undefined;
  private polling = false;

  constructor(
    private readonly channels: string,
    private readonly handler: Handler,
  ) {}

  start(): void {
    this.connect();
  }

  close(): void {
    this.stopped = true;
    this.stopPolling();
    if (this.reconnectTimer) window.clearTimeout(this.reconnectTimer);
    this.socket?.close();
    this.socket = null;
  }

  private setStatus(status: BusStatus): void {
    this.status.value = status;
  }

  private endpoint(): string {
    const params = new URLSearchParams({ channels: this.channels });
    if (this.last) params.set("after", String(this.last));
    return `/web/bus?${params.toString()}`;
  }

  private connect(): void {
    if (this.stopped) return;
    this.setStatus("connecting");
    if (!("WebSocket" in window)) {
      this.startPolling();
      return;
    }
    let socket: WebSocket;
    try {
      const scheme = location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${scheme}://${location.host}${this.endpoint()}`);
    } catch {
      this.startPolling();
      return;
    }
    this.socket = socket;
    const helloTimer = window.setTimeout(() => {
      if (this.status.value === "connecting") socket.close();
    }, 6000);

    socket.addEventListener("open", () => {
      this.stopPolling();
      /* `live` waits for the server's hello, which carries the baseline id.
         Marking the socket live before that can skip a message published in
         the handshake window. */
    });

    socket.addEventListener("message", (event: MessageEvent<string>) => {
      try {
        const data = JSON.parse(event.data) as {
          type?: string;
          latest?: number;
        } & Partial<BusEnvelope>;
        if (data.type === "hello") {
          window.clearTimeout(helloTimer);
          this.last = Math.max(this.last, Number(data.latest ?? 0));
          this.setStatus("live");
          return;
        }
        if (data.type === "bus" && typeof data.id === "number") {
          this.accept(data as BusEnvelope);
        }
      } catch {
        /* ignore malformed frames; the next one may be valid */
      }
    });

    socket.addEventListener("close", () => {
      window.clearTimeout(helloTimer);
      this.socket = null;
      if (this.stopped) return;
      this.setStatus("offline");
      this.startPolling();
      this.scheduleReconnect();
    });

    socket.addEventListener("error", () => {
      socket.close();
    });
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer || this.stopped) return;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = undefined;
      this.connect();
    }, 2000);
  }

  private accept(message: BusEnvelope): void {
    if (message.id <= this.last) return;
    this.last = message.id;
    this.handler(message);
  }

  private startPolling(): void {
    if (this.polling || this.stopped) return;
    this.polling = true;
    this.setStatus("polling");
    const tick = async (): Promise<void> => {
      if (this.stopped || !this.polling) return;
      try {
        const response = await fetch(this.endpoint(), { credentials: "same-origin" });
        if (response.ok) {
          const data = (await response.json()) as {
            latest?: number;
            messages?: BusEnvelope[];
          };
          for (const message of data.messages ?? []) this.accept(message);
          this.last = Math.max(this.last, Number(data.latest ?? 0));
          if (!this.socket) this.setStatus("polling");
        } else {
          this.setStatus("offline");
        }
      } catch {
        this.setStatus("offline");
      }
      this.pollTimer = window.setTimeout(() => void tick(), 4000);
    };
    void tick();
  }

  private stopPolling(): void {
    this.polling = false;
    if (this.pollTimer) window.clearTimeout(this.pollTimer);
    this.pollTimer = undefined;
  }
}

export function busStatusLabel(status: BusStatus): string {
  switch (status) {
    case "live":
      return "Realtime connected";
    case "polling":
      return "Realtime polling";
    case "offline":
      return "Realtime offline";
    default:
      return "Realtime connecting";
  }
}
