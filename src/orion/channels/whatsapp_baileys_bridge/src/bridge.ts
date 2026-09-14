/**
 * Orion WhatsApp Baileys Bridge
 *
 * JSON-line protocol on stdio:
 *
 * Input commands (stdin):
 *   {"type":"send","jid":"<jid>","text":"<message>"}
 *   {"type":"disconnect"}
 *
 * Output events (stdout):
 *   {"type":"message","jid":"<jid>","sender":"<sender>","text":"<text>","message_id":"<id>"}
 *   {"type":"status","status":"connected"|"disconnected"}
 *   {"type":"qr","data":"<qr-string>"}
 *   {"type":"pairing_code","data":"<8-char-code>"}
 *   {"type":"error","message":"<description>"}
 *
 * CLI args:
 *   --auth-dir <dir>      Directory for auth state persistence.
 *   --pair-phone <number> Digits-only phone with country code (e.g. 919876543210)
 *                         to use the Pairing Code flow instead of QR — type the
 *                         resulting code into WhatsApp's own "Link a Device" screen.
 */

import makeWASocket, {
  DisconnectReason,
  fetchLatestBaileysVersion,
  useMultiFileAuthState,
  WASocket,
} from "@whiskeysockets/baileys";
import * as readline from "readline";
import * as qrcodeTerminal from "qrcode-terminal";
import pino from "pino";

// Debug-level logger — the default level was too sparse to see WHY the
// connection was closing (just one "connection closed" line, no reason).
// This surfaces the actual protocol frames exchanged with WhatsApp's server.
const log = pino({ level: "debug" });

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function emit(event: Record<string, unknown>): void {
  process.stdout.write(JSON.stringify(event) + "\n");
}

function parseArgs(): { authDir: string; pairPhone: string } {
  const args = process.argv.slice(2);
  let authDir = "./auth";
  let pairPhone = "";
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--auth-dir" && i + 1 < args.length) {
      authDir = args[i + 1];
    } else if (args[i] === "--pair-phone" && i + 1 < args.length) {
      // Digits only, country code + number, e.g. 919876543210 for India.
      pairPhone = args[i + 1];
    }
  }
  return { authDir, pairPhone };
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  process.on("uncaughtException", (err) => {
    process.stderr.write("DEBUG uncaughtException: " + String(err?.stack || err) + "\n");
  });
  process.on("unhandledRejection", (err) => {
    process.stderr.write("DEBUG unhandledRejection: " + String((err as any)?.stack || err) + "\n");
  });

  const { authDir, pairPhone } = parseArgs();

  // Parent-liveness watchdog.
  //
  // WhatsApp allows exactly one session per linked device, so a bridge that
  // outlives the backend that spawned it is actively harmful: the next
  // backend starts a second bridge, the two evict each other in a loop, and
  // inbound messages stop arriving. Closing stdin normally ends this process,
  // but that did not always fire when the parent was force-killed and real
  // orphans were observed holding the session. Polling for the parent's
  // disappearance is a cheap, definitive backstop.
  const parentPid = process.ppid;
  setInterval(() => {
    try {
      // Signal 0 performs the permission/existence check without delivering.
      process.kill(parentPid, 0);
    } catch {
      process.stderr.write("Parent process gone — exiting so the session is released.\n");
      process.exit(0);
    }
  }, 10_000).unref();

  const { state, saveCreds } = await useMultiFileAuthState(authDir);

  // Without this, makeWASocket() falls back to a hardcoded default WA
  // protocol version baked into this Baileys release, which WhatsApp's
  // servers can silently reject (observed here: connection closes instantly
  // with no error at all — no QR, nothing). Fetching the live version fixes it.
  const { version } = await fetchLatestBaileysVersion();
  process.stderr.write("Using WA version: " + JSON.stringify(version) + "\n");

  let sock: WASocket | null = null;

  let pairingRequested = false;
  let reconnectAttempt = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  function scheduleReconnect(): void {
    if (reconnectTimer) return; // a retry is already pending
    const delayMs = Math.min(30_000, 1_000 * 2 ** reconnectAttempt);
    reconnectAttempt += 1;
    process.stderr.write("DEBUG reconnect attempt " + reconnectAttempt + " in " + delayMs + "ms\n");
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      try {
        startSocket();
      } catch (e) {
        process.stderr.write("DEBUG startSocket() threw: " + String((e as any)?.stack || e) + "\n");
        scheduleReconnect();
      }
    }, delayMs);
  }

  function startSocket(): void {
    // Retire the previous socket so its handlers can never fire again.
    if (sock) {
      try {
        sock.ev.removeAllListeners("connection.update");
        sock.ev.removeAllListeners("messages.upsert");
        sock.ev.removeAllListeners("creds.update");
        sock.end(undefined);
      } catch {
        /* already closed */
      }
    }
    sock = makeWASocket({
      auth: state,
      version,
      printQRInTerminal: false,
      logger: log,
    });

    sock.ev.on("creds.update", saveCreds);

    // Pairing-code flow: an alternative to QR scanning — generates a short
    // code to type into WhatsApp's own "Link a Device" screen instead.
    if (pairPhone && !pairingRequested && !sock.authState.creds.registered) {
      pairingRequested = true;
      sock.requestPairingCode(pairPhone).then((code) => {
        process.stderr.write("PAIRING CODE: " + code + "\n");
        emit({ type: "pairing_code", data: code });
      }).catch((err) => {
        process.stderr.write("DEBUG pairing code request failed: " + String(err?.stack || err) + "\n");
      });
    }

    sock.ev.on("connection.update", (update) => {
      const { connection, lastDisconnect, qr } = update;
      process.stderr.write("DEBUG update: " + JSON.stringify(update) + "\n");

      if (qr) {
        // Show QR in stderr for local debugging and emit structured event.
        qrcodeTerminal.generate(qr, { small: true }, (code: string) => {
          process.stderr.write(code + "\n");
        });
        emit({ type: "qr", data: qr });
      }

      if (connection === "close") {
        // No DisconnectReason.unknown exists in this Baileys version — 0 is a
        // safe sentinel that won't match any real reason code below.
        const statusCode =
          (lastDisconnect?.error as any)?.output?.statusCode ?? 0;
        process.stderr.write(
          "DEBUG close: statusCode=" + statusCode +
          " error=" + String(lastDisconnect?.error) + "\n"
        );

        if (statusCode === DisconnectReason.loggedOut) {
          emit({ type: "status", status: "disconnected" });
          emit({ type: "error", message: "Logged out from WhatsApp" });
        } else {
          // Transient failure (network drop, server restart): retry with a
          // growing delay, one socket at a time. Retrying synchronously used
          // to spawn a new socket on every close while the old ones kept
          // firing, so a 13-second DNS outage became thousands of attempts.
          emit({ type: "status", status: "reconnecting" });
          scheduleReconnect();
        }
      } else if (connection === "open") {
        reconnectAttempt = 0;
        emit({ type: "status", status: "connected" });
      }
    });

    sock.ev.on("messages.upsert", (m) => {
      // Baileys tags this batch "notify" for a genuinely live message and
      // "append"/"replace" when it's replaying history -- most importantly,
      // the offline backlog WhatsApp redelivers on every reconnect, which
      // includes messages the real WhatsApp app already showed as read
      // *before* this process ever restarted. Without this check, every
      // reconnect (e.g. after the backend restarts) replayed that backlog
      // through the exact same path as a live message, so already-read
      // messages got auto-replied to all over again -- observed live as a
      // burst of duplicate auto-replies sent to a real contact.
      if (m.type !== "notify") {
        process.stderr.write(
          "DEBUG skipped " + m.messages.length + " message(s), upsert type=" + m.type +
          " (history replay, not live)\n"
        );
        return;
      }

      // Second, independent guard: a message is only "live" if it actually
      // arrived recently. Belt-and-braces against any Baileys version or
      // reconnect path that mislabels a replay as "notify".
      const STALE_AFTER_SECONDS = 120;
      const nowSec = Date.now() / 1000;

      for (const msg of m.messages) {
        if (!msg.message) continue;

        // A message the owner sent themselves, from their phone or any
        // other linked device (not through Orion). Surfaced as its own
        // event instead of silently dropped, so the Python side can tell
        // "the owner is already handling this conversation" and cancel a
        // pending auto-reply instead of sending a redundant/contradictory
        // one after the owner already replied in person.
        if (msg.key.fromMe) {
          emit({ type: "own_message", jid: msg.key.remoteJid || "" });
          continue;
        }

        const ts = typeof msg.messageTimestamp === "number"
          ? msg.messageTimestamp
          : Number(msg.messageTimestamp?.toString?.() ?? NaN);
        if (Number.isFinite(ts) && nowSec - ts > STALE_AFTER_SECONDS) {
          process.stderr.write(
            "DEBUG skipped stale message id=" + msg.key.id +
            " age=" + Math.round(nowSec - ts) + "s\n"
          );
          continue;
        }

        const text =
          msg.message.conversation ||
          msg.message.extendedTextMessage?.text ||
          "";
        if (!text) continue;

        emit({
          type: "message",
          jid: msg.key.remoteJid || "",
          sender: msg.key.participant || msg.key.remoteJid || "",
          text,
          message_id: msg.key.id || "",
        });
      }
    });
  }

  startSocket();

  // -----------------------------------------------------------------------
  // Stdin command processing
  // -----------------------------------------------------------------------

  const rl = readline.createInterface({ input: process.stdin });

  rl.on("line", async (line: string) => {
    let cmd: Record<string, unknown>;
    try {
      cmd = JSON.parse(line);
    } catch {
      emit({ type: "error", message: "Invalid JSON on stdin" });
      return;
    }

    if (cmd.type === "send" && sock) {
      try {
        await sock.sendMessage(cmd.jid as string, { text: cmd.text as string });
      } catch (err: any) {
        emit({ type: "error", message: `Send failed: ${err.message}` });
      }
    } else if (cmd.type === "disconnect") {
      if (sock) {
        sock.end(undefined);
      }
      emit({ type: "status", status: "disconnected" });
      process.exit(0);
    }
  });

  rl.on("close", () => {
    if (sock) {
      sock.end(undefined);
    }
    process.exit(0);
  });
}

main().catch((err) => {
  emit({ type: "error", message: `Fatal: ${err.message}` });
  process.exit(1);
});
