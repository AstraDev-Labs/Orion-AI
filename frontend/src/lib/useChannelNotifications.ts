import { useEffect, useRef } from 'react';
import { getBase, isTauri } from './api';

interface ChannelNotifyPayload {
  channel: string;
  sender: string;
  preview: string;
  priority: 'emergency' | 'important' | 'normal';
  away: boolean;
  conversation_id: string;
}

const PRIORITY_LABEL: Record<string, string> = {
  emergency: 'Emergency',
  important: 'Important',
  normal: 'New message',
};

function buildWsUrl(): string {
  const base = getBase();
  let origin: string;
  if (base) {
    origin = base.replace(/^http/, 'ws');
  } else {
    const loc = window.location;
    origin = `${loc.protocol === 'https:' ? 'wss:' : 'ws:'}//${loc.host}`;
  }
  // No agent_id query param -- events without an agent_id in their payload
  // (like channel_message_notify) are only forwarded to unfiltered clients.
  return `${origin}/v1/agents/events`;
}

/**
 * Subscribes to inbound-channel-message notifications and raises a native
 * desktop toast for each one, tagged with priority. Mount once at the app
 * root so it's always listening regardless of the active view.
 */
export function useChannelNotifications(): void {
  const permissionRef = useRef<boolean | null>(null);

  useEffect(() => {
    if (!isTauri()) return;

    let closed = false;
    let ws: WebSocket | null = null;
    let retry = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    async function ensurePermission(): Promise<boolean> {
      if (permissionRef.current !== null) return permissionRef.current;
      try {
        const { isPermissionGranted, requestPermission } = await import(
          '@tauri-apps/plugin-notification'
        );
        let granted = await isPermissionGranted();
        if (!granted) {
          const result = await requestPermission();
          granted = result === 'granted';
        }
        permissionRef.current = granted;
        return granted;
      } catch {
        permissionRef.current = false;
        return false;
      }
    }

    async function raiseToast(payload: ChannelNotifyPayload) {
      const granted = await ensurePermission();
      if (!granted) return;
      try {
        const { sendNotification } = await import('@tauri-apps/plugin-notification');
        const label = PRIORITY_LABEL[payload.priority] || 'New message';
        sendNotification({
          title: `${label} — ${payload.channel} (${payload.sender})`,
          body: payload.away
            ? `${payload.preview}\n(auto-replied while you were away)`
            : payload.preview,
        });
      } catch {
        // Notification plugin unavailable -- nothing else to do.
      }
    }

    const connect = () => {
      if (closed) return;
      try {
        ws = new WebSocket(buildWsUrl());
      } catch {
        schedule();
        return;
      }
      ws.onopen = () => {
        retry = 0;
      };
      ws.onmessage = (msg) => {
        try {
          const payload = JSON.parse(msg.data) as { type: string; data: ChannelNotifyPayload };
          if (payload.type === 'channel_message_notify') {
            raiseToast(payload.data);
          }
        } catch {
          // ignore malformed payload
        }
      };
      ws.onclose = () => {
        if (!closed) schedule();
      };
      ws.onerror = () => {
        ws?.close();
      };
    };

    const schedule = () => {
      if (closed) return;
      const delay = Math.min(30000, 1000 * 2 ** Math.min(retry, 5));
      retry += 1;
      reconnectTimer = setTimeout(connect, delay);
    };

    connect();

    return () => {
      closed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, []);
}
