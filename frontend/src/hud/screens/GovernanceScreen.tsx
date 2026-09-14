import { useEffect, useRef, useState } from 'react';
import QRCode from 'qrcode';
import {
  fetchConfig,
  fetchTools,
  toggleTool,
  fetchAutoReply,
  updateAutoReply,
  fetchLearningStatus,
  runLearningCycle,
  fetchWhatsAppQr,
  connectWhatsApp,
  fetchGeneratedTools,
  removeGeneratedTool,
  toolLabel,
  type OrionConfigView,
  type ToolRow,
  type LearningStatus,
  type GeneratedToolRow,
} from '../api';

/** Real WhatsApp pairing: shows a live QR while unlinked, "Connected" once
 * actually linked -- backed by the bridge's genuine handshake state
 * (server/routes.py's /v1/channels/whatsapp/qr), never a placeholder code. */
export function WhatsAppConnectPanel() {
  const [status, setStatus] = useState<string>('reading');
  const [qr, setQr] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState('');
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  const load = () =>
    fetchWhatsAppQr()
      .then((d) => {
        setStatus(d.status);
        setQr(d.qr);
      })
      .catch(() => {});

  useEffect(() => {
    load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (qr && canvasRef.current) {
      QRCode.toCanvas(canvasRef.current, qr, { width: 200, margin: 1 }).catch(() => {});
    }
  }, [qr]);

  const onConnect = async () => {
    setConnecting(true);
    setError('');
    try {
      await connectWhatsApp();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Connect failed');
    } finally {
      setConnecting(false);
    }
  };

  const connected = status === 'connected';
  const notConfigured = status === 'not_configured';

  return (
    <div style={{ marginTop: 14 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 20,
          padding: '12px 0',
          borderBottom: '1px solid rgba(248,244,244,0.08)',
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div style={{ fontFamily: 'var(--font-heading)', fontSize: 18 }}>WhatsApp</div>
          <div style={{ fontSize: 11, color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>
            {notConfigured
              ? 'Channel not configured — set channel.enabled = true in config.toml.'
              : connected
                ? 'Linked to your WhatsApp.'
                : status === 'connecting'
                  ? 'Waiting for you to scan the code below…'
                  : 'Not linked.'}
          </div>
        </div>
        {!connected && !notConfigured && (
          <button className="holo-ghost-btn" onClick={onConnect} disabled={connecting} style={{ flexShrink: 0 }}>
            {connecting ? 'Starting…' : 'Connect'}
          </button>
        )}
        {connected && (
          <span
            style={{
              flexShrink: 0,
              fontSize: 9.5,
              letterSpacing: '0.14em',
              textTransform: 'uppercase',
              color: 'var(--color-accent-300)',
            }}
          >
            ● Connected
          </span>
        )}
      </div>

      {error && <div style={{ color: '#e06b5c', fontSize: 11.5, marginTop: 10 }}>{error}</div>}

      {!connected && qr && (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, marginTop: 16 }}>
          <div style={{ padding: 10, background: '#fff', border: '1px solid rgba(182,130,53,0.4)' }}>
            <canvas ref={canvasRef} />
          </div>
          <div style={{ fontSize: 11, color: 'var(--color-neutral-600)', textAlign: 'center', maxWidth: 280 }}>
            Open WhatsApp → Settings → Linked Devices → Link a Device, and scan this code.
            It refreshes automatically if it expires.
          </div>
        </div>
      )}
    </div>
  );
}

/** Governance — real engine config, real tool toggles, the auto-reply master switch + allowlist, and the self-improvement pipeline. */
export function GovernanceScreen() {
  const [config, setConfig] = useState<OrionConfigView | null>(null);
  const [tools, setTools] = useState<ToolRow[]>([]);

  const [autoReplyEnabled, setAutoReplyEnabled] = useState<boolean | null>(null);
  const [allowlist, setAllowlist] = useState<string[]>([]);
  const [newContact, setNewContact] = useState('');
  const [autoReplyBusy, setAutoReplyBusy] = useState(false);

  const [learning, setLearning] = useState<LearningStatus | null>(null);
  const [learningBusy, setLearningBusy] = useState(false);
  const [learningError, setLearningError] = useState('');
  const [justRan, setJustRan] = useState(false);

  const [generatedTools, setGeneratedTools] = useState<GeneratedToolRow[]>([]);
  const [removingTool, setRemovingTool] = useState<string | null>(null);
  const [removeNotice, setRemoveNotice] = useState('');

  const loadLearning = () => fetchLearningStatus().then(setLearning).catch(() => {});
  const loadGeneratedTools = () =>
    fetchGeneratedTools()
      .then((d) => setGeneratedTools(d.tools))
      .catch(() => {});

  const removeTool = async (name: string) => {
    setRemovingTool(name);
    setRemoveNotice('');
    try {
      const res = await removeGeneratedTool(name);
      setRemoveNotice(
        res.restart === 'scheduled'
          ? `Removed '${name}' — backend is restarting now.`
          : `Removed '${name}', but the automatic restart failed. Restart Orion manually.`
      );
      await loadGeneratedTools();
    } catch (e) {
      setRemoveNotice(e instanceof Error ? e.message : `Failed to remove '${name}'`);
    } finally {
      setRemovingTool(null);
    }
  };

  const runNow = async () => {
    setLearningBusy(true);
    setLearningError('');
    setJustRan(false);
    try {
      // Await the real result directly, rather than only refetching status
      // afterward -- when nothing has changed since the last run (e.g. no
      // new traces yet), the "skipped" result looks byte-identical to
      // whatever was already on screen, so a click can look like it did
      // nothing at all even though it genuinely ran.
      await runLearningCycle();
      setJustRan(true);
      setTimeout(() => setJustRan(false), 4000);
    } catch (e) {
      setLearningError(e instanceof Error ? e.message : 'run failed');
    } finally {
      setLearningBusy(false);
      loadLearning();
    }
  };

  useEffect(() => {
    fetchConfig().then(setConfig).catch(() => {});
    fetchTools().then((d) => setTools(d.tools)).catch(() => {});
    fetchAutoReply()
      .then((d) => {
        setAutoReplyEnabled(d.enabled);
        setAllowlist(d.allowlist);
      })
      .catch(() => {});
    loadLearning();
    loadGeneratedTools();
    const id = setInterval(loadLearning, 10000);
    return () => clearInterval(id);
  }, []);

  const toggleAutoReply = async () => {
    const next = !autoReplyEnabled;
    setAutoReplyEnabled(next);
    setAutoReplyBusy(true);
    try {
      await updateAutoReply({ enabled: next });
    } catch {
      setAutoReplyEnabled(!next);
    } finally {
      setAutoReplyBusy(false);
    }
  };

  const addContact = async () => {
    const id = newContact.trim();
    if (!id || allowlist.includes(id)) return;
    const next = [...allowlist, id];
    setAllowlist(next);
    setNewContact('');
    try {
      await updateAutoReply({ allowlist: next });
    } catch {
      setAllowlist(allowlist);
    }
  };

  const removeContact = async (id: string) => {
    const next = allowlist.filter((c) => c !== id);
    setAllowlist(next);
    try {
      await updateAutoReply({ allowlist: next });
    } catch {
      setAllowlist(allowlist);
    }
  };

  const toggle = async (tool: ToolRow) => {
    setTools((prev) => prev.map((t) => (t.name === tool.name ? { ...t, enabled: !t.enabled } : t)));
    try {
      await toggleTool(tool.name, !tool.enabled);
    } catch {
      setTools((prev) => prev.map((t) => (t.name === tool.name ? { ...t, enabled: tool.enabled } : t)));
    }
  };

  const engineRows = config
    ? [
        { label: 'Model', hint: 'The weights currently resident', value: config.model },
        { label: 'Engine', hint: 'Inference backend', value: config.engine },
        { label: 'Temperature', hint: 'Higher wanders, lower holds the line', value: String(config.temperature) },
        { label: 'Ceiling', hint: 'Maximum tokens per reply', value: String(config.max_tokens) },
        { label: 'Vault', hint: 'Where notes are written', value: config.obsidian_dir || '(not set)' },
      ]
    : [];

  return (
    <div className="holo-panel holo-boot-in" style={{ position: 'absolute', inset: 0, overflowY: 'auto', padding: '20px 30px 24px' }}>
      <div className="holo-corner holo-corner-tl" />
      <div className="holo-corner holo-corner-br" />
      <div style={{ paddingBottom: 13, borderBottom: '1px solid rgba(182,130,53,0.26)', marginBottom: 20 }}>
        <div className="holo-kicker" style={{ marginBottom: 5 }}>
          Charter · 06
        </div>
        <h2 style={{ fontSize: 26 }}>Governance</h2>
      </div>

      <div style={{ maxWidth: 640 }}>
        <h3
          style={{
            fontSize: 11,
            fontWeight: 500,
            letterSpacing: '0.2em',
            textTransform: 'uppercase',
            color: 'var(--color-neutral-600)',
            marginBottom: 12,
          }}
        >
          Engine
        </h3>
        {!config && <div style={{ color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>Reading…</div>}
        {engineRows.map((r) => (
          <div
            key={r.label}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 20,
              padding: '12px 0',
              borderBottom: '1px solid rgba(248,244,244,0.08)',
            }}
          >
            <div style={{ minWidth: 0 }}>
              <div style={{ fontFamily: 'var(--font-heading)', fontSize: 18 }}>{r.label}</div>
              <div style={{ fontSize: 11, color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>{r.hint}</div>
            </div>
            <div
              style={{
                flexShrink: 0,
                border: '1px solid rgba(182,130,53,0.44)',
                padding: '5px 12px',
                fontSize: 13,
                color: 'var(--color-accent-300)',
                whiteSpace: 'nowrap',
                maxWidth: 260,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {r.value}
            </div>
          </div>
        ))}

        <h3
          style={{
            fontSize: 11,
            fontWeight: 500,
            letterSpacing: '0.2em',
            textTransform: 'uppercase',
            color: 'var(--color-neutral-600)',
            margin: '24px 0 12px',
          }}
        >
          Tools ({tools.filter((t) => t.enabled).length} / {tools.length} enabled)
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
          {tools.map((t) => (
            <button
              key={t.name}
              onClick={() => toggle(t)}
              title={t.description}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: 8,
                padding: '8px 10px',
                border: `1px solid ${t.enabled ? 'rgba(182,130,53,0.55)' : 'rgba(182,130,53,0.2)'}`,
                background: 'transparent',
                color: t.enabled ? 'var(--color-accent-300)' : 'var(--color-neutral-600)',
                fontSize: 11.5,
                cursor: 'pointer',
                textAlign: 'left',
              }}
            >
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{toolLabel(t.name)}</span>
              <span style={{ fontSize: 9, letterSpacing: '0.1em' }}>{t.enabled ? 'ON' : 'OFF'}</span>
            </button>
          ))}
        </div>
        <p style={{ marginTop: 22, fontSize: 11.5, color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>
          Engine changes reach the running backend immediately; tool changes apply after the next backend restart.
        </p>

        <h3
          style={{
            fontSize: 11,
            fontWeight: 500,
            letterSpacing: '0.2em',
            textTransform: 'uppercase',
            color: 'var(--color-neutral-600)',
            margin: '28px 0 12px',
          }}
        >
          Conduits
        </h3>
        <WhatsAppConnectPanel />

        <h3
          style={{
            fontSize: 11,
            fontWeight: 500,
            letterSpacing: '0.2em',
            textTransform: 'uppercase',
            color: 'var(--color-neutral-600)',
            margin: '28px 0 12px',
          }}
        >
          Auto-reply
        </h3>

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 20,
            padding: '12px 0',
            borderBottom: '1px solid rgba(248,244,244,0.08)',
          }}
        >
          <div style={{ minWidth: 0 }}>
            <div style={{ fontFamily: 'var(--font-heading)', fontSize: 18 }}>Reply while away</div>
            <div style={{ fontSize: 11, color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>
              Master switch — off means Orion still notifies you, but never answers on your behalf
            </div>
          </div>
          <button
            onClick={toggleAutoReply}
            disabled={autoReplyEnabled === null || autoReplyBusy}
            className="holo-ghost-btn"
            style={{
              flexShrink: 0,
              color: autoReplyEnabled ? 'var(--color-accent-300)' : 'var(--color-neutral-600)',
              borderColor: autoReplyEnabled ? 'var(--color-accent)' : 'rgba(182,130,53,0.3)',
            }}
          >
            {autoReplyEnabled === null ? 'Reading…' : autoReplyEnabled ? 'On' : 'Off'}
          </button>
        </div>

        <div style={{ padding: '14px 0 4px' }}>
          <div style={{ fontFamily: 'var(--font-heading)', fontSize: 18, marginBottom: 3 }}>Allowed contacts</div>
          <div style={{ fontSize: 11, color: 'var(--color-neutral-600)', fontStyle: 'italic', marginBottom: 12 }}>
            {allowlist.length === 0
              ? 'Empty — Orion will auto-reply to anyone. Add a number below to restrict it.'
              : 'Only these senders get an auto-reply; everyone else is notified but not answered.'}
          </div>

          <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
            <input
              value={newContact}
              onChange={(e) => setNewContact(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  addContact();
                }
              }}
              placeholder="Phone number or JID, e.g. 919876543210@s.whatsapp.net"
              style={{
                flex: 1,
                minWidth: 0,
                background: 'transparent',
                border: '1px solid rgba(182,130,53,0.34)',
                padding: '8px 11px',
                fontSize: 13,
                color: 'var(--color-neutral-100)',
                fontFamily: 'var(--font-body)',
              }}
            />
            <button className="holo-ghost-btn" onClick={addContact} disabled={!newContact.trim()}>
              Add
            </button>
          </div>

          {allowlist.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {allowlist.map((id) => (
                <div
                  key={id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 10,
                    padding: '7px 11px',
                    border: '1px solid rgba(182,130,53,0.24)',
                    fontSize: 12.5,
                  }}
                >
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{id}</span>
                  <button
                    onClick={() => removeContact(id)}
                    style={{
                      flexShrink: 0,
                      background: 'transparent',
                      border: 0,
                      color: 'var(--color-neutral-600)',
                      cursor: 'pointer',
                      fontSize: 11,
                      letterSpacing: '0.1em',
                      textTransform: 'uppercase',
                    }}
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        <h3
          style={{
            fontSize: 11,
            fontWeight: 500,
            letterSpacing: '0.2em',
            textTransform: 'uppercase',
            color: 'var(--color-neutral-600)',
            margin: '28px 0 12px',
          }}
        >
          Self-improvement
        </h3>

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 20,
            padding: '12px 0',
            borderBottom: '1px solid rgba(248,244,244,0.08)',
          }}
        >
          <div style={{ minWidth: 0 }}>
            <div style={{ fontFamily: 'var(--font-heading)', fontSize: 18 }}>Run a learning cycle now</div>
            <div style={{ fontSize: 11, color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>
              {learning === null
                ? 'Reading…'
                : !learning.active
                  ? learning.reason || 'Not active.'
                  : `${learning.trace_count} traces captured · normally runs after ${Math.round((learning.minimum_idle_seconds || 0) / 60)}m idle`}
            </div>
          </div>
          <button
            className="holo-ghost-btn"
            onClick={runNow}
            disabled={!learning?.active || learning?.running || learningBusy}
            style={{ flexShrink: 0 }}
          >
            {learning?.running || learningBusy ? 'Running…' : 'Run now'}
          </button>
        </div>

        {learningError && (
          <div style={{ color: '#e06b5c', fontSize: 11.5, marginTop: 10 }}>{learningError}</div>
        )}

        {justRan && !learningError && (
          <div style={{ color: 'var(--color-accent-300)', fontSize: 11.5, marginTop: 10 }}>
            ✓ Cycle ran just now{learning?.last_run_at ? ` — ${new Date(learning.last_run_at * 1000).toLocaleTimeString()}` : ''}
          </div>
        )}

        {learning?.last_result && (
          <div style={{ marginTop: 14, fontSize: 12.5, lineHeight: 1.8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ color: 'var(--color-neutral-600)' }}>
                Last cycle{learning.last_run_at ? ` · ${new Date(learning.last_run_at * 1000).toLocaleTimeString()}` : ''}
              </span>
              <span
                style={{
                  color:
                    learning.last_result.status === 'completed'
                      ? 'var(--color-accent-300)'
                      : learning.last_result.status === 'rejected'
                        ? '#e06b5c'
                        : 'var(--color-neutral-600)',
                  textTransform: 'uppercase',
                  fontSize: 10.5,
                  letterSpacing: '0.1em',
                }}
              >
                {learning.last_result.status}
              </span>
            </div>
            {learning.last_result.status === 'skipped' ? (
              <div style={{ color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>
                {learning.last_result.reason || 'No training data available yet.'}
              </div>
            ) : (
              <>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: 'var(--color-neutral-600)' }}>SFT pairs</span>
                  <span>
                    {learning.last_result.sft_pairs ?? 0}
                    {(learning.last_result.web_sft_pairs ?? 0) > 0
                      ? ` (${learning.last_result.web_sft_pairs} from web research)`
                      : ''}
                  </span>
                </div>
                {learning.last_result.baseline_score != null && (
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--color-neutral-600)' }}>Eval score</span>
                    <span>
                      {(learning.last_result.baseline_score * 100).toFixed(0)}% →{' '}
                      {((learning.last_result.post_score ?? 0) * 100).toFixed(0)}%
                    </span>
                  </div>
                )}
                {learning.last_result.reason && (
                  <div style={{ color: 'var(--color-neutral-600)', fontStyle: 'italic', marginTop: 4 }}>
                    {learning.last_result.reason}
                  </div>
                )}
              </>
            )}
          </div>
        )}

        <h3
          style={{
            fontSize: 11,
            fontWeight: 500,
            letterSpacing: '0.2em',
            textTransform: 'uppercase',
            color: 'var(--color-neutral-600)',
            margin: '28px 0 12px',
          }}
        >
          Generated tools ({generatedTools.length})
        </h3>
        <p style={{ fontSize: 11.5, color: 'var(--color-neutral-600)', fontStyle: 'italic', marginBottom: 12 }}>
          Tools Orion wrote itself after you approved them via propose_new_tool. Each one only
          became callable once the backend restarted — remove any you don't want.
        </p>

        {generatedTools.length === 0 && (
          <div style={{ color: 'var(--color-neutral-600)', fontStyle: 'italic', fontSize: 12.5 }}>
            None yet — ask Orion for something with no matching tool and it may propose one.
          </div>
        )}

        {generatedTools.map((t) => (
          <div
            key={t.name}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 20,
              padding: '12px 0',
              borderBottom: '1px solid rgba(248,244,244,0.08)',
            }}
          >
            <div style={{ minWidth: 0 }}>
              <div style={{ fontFamily: 'var(--font-heading)', fontSize: 16 }}>{t.name}</div>
              <div style={{ fontSize: 11, color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>
                {t.description || '(no description)'}
                {!t.registered && ' — written to disk, not yet loaded (restart pending)'}
                {t.created_at ? ` · ${new Date(t.created_at * 1000).toLocaleString()}` : ''}
              </div>
            </div>
            <button
              onClick={() => removeTool(t.name)}
              disabled={removingTool === t.name}
              style={{
                flexShrink: 0,
                background: 'transparent',
                border: '1px solid rgba(224,107,92,0.4)',
                color: '#e06b5c',
                cursor: 'pointer',
                padding: '5px 12px',
                fontSize: 11,
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
              }}
            >
              {removingTool === t.name ? 'Removing…' : 'Remove'}
            </button>
          </div>
        ))}

        {removeNotice && (
          <div style={{ color: 'var(--color-accent-300)', fontSize: 11.5, marginTop: 10 }}>
            {removeNotice}
          </div>
        )}
      </div>
    </div>
  );
}

export default GovernanceScreen;
