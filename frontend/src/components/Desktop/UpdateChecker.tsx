import { useEffect } from 'react';
import { isTauri } from '../../lib/api';
import { toast } from 'sonner';

type AppUpdate = { version: string; current: string; notes: string };
type UpdateProgress = { stage: 'downloading' | 'verifying' | 'installing'; downloaded: number; total: number };

const TOAST_ID = 'app-update';

/**
 * Offers new versions of Orion.
 *
 * Installs made with the Windows installer are updated by the app itself
 * (src-tauri/src/app_update.rs): it checks in the background, sends a system
 * notification, and emits `app-update-available`, shown here as an
 * "Update now" prompt. Other builds use Tauri's updater plugin.
 */
export function UpdateChecker() {
  useEffect(() => {
    if (!isTauri() || import.meta.env.VITE_OPENORION_NO_UPDATER) return;
    let unlisten: (() => void) | undefined;
    let cancelled = false;

    void (async () => {
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        const { listen } = await import('@tauri-apps/api/event');
        if (!(await invoke<boolean>('app_update_supported'))) {
          await checkWithTauriUpdater();
          return;
        }

        const install = async () => {
          toast.loading('Downloading the update…', { id: TOAST_ID, duration: Infinity });
          const stopProgress = await listen<UpdateProgress>('app-update-progress', ({ payload }) => {
            if (payload.stage === 'downloading') {
              const pct = payload.total ? Math.round((payload.downloaded / payload.total) * 100) : null;
              toast.loading(pct === null ? 'Downloading the update…' : `Downloading the update… ${pct}%`, { id: TOAST_ID, duration: Infinity });
            } else if (payload.stage === 'verifying') {
              toast.loading('Checking the update is genuine…', { id: TOAST_ID, duration: Infinity });
            } else {
              toast.loading('Installing. Orion will close and reopen by itself.', { id: TOAST_ID, duration: Infinity });
            }
          });
          try {
            await invoke('install_app_update');
          } catch (err) {
            toast.error('Orion could not update', { id: TOAST_ID, description: String(err), duration: 10000 });
          } finally {
            stopProgress();
          }
        };

        const offer = (update: AppUpdate) => {
          toast(`Orion ${update.version} is available`, {
            id: TOAST_ID,
            duration: Infinity,
            description: update.notes
              ? update.notes
              : `You have ${update.current}. Updating takes a minute and keeps your settings and memories.`,
            action: {
              label: 'Update now',
              onClick: (event) => {
                // Keep this toast: it becomes the progress and error message.
                // Sonner otherwise dismisses it on click, and the dismissal
                // also swallowed those later messages (they share its id).
                event.preventDefault();
                void install();
              },
            },
            cancel: { label: 'Later', onClick: () => {} },
          });
        };

        const stop = await listen<AppUpdate>('app-update-available', ({ payload }) => offer(payload));
        if (cancelled) stop();
        else unlisten = stop;
        const known = await invoke<AppUpdate | null>('get_app_update');
        if (known && !cancelled) offer(known);
      } catch {
        // updates unavailable in this build: non-fatal
      }
    })();

    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, []);

  return null;
}

async function checkWithTauriUpdater() {
  const { check } = await import('@tauri-apps/plugin-updater');
  const update = await check();
  if (!update?.available) return;
  toast(`Orion ${update.version} is available`, {
    id: TOAST_ID,
    duration: Infinity,
    action: {
      label: 'Update now',
      onClick: async () => {
        try {
          await update.downloadAndInstall();
          const { relaunch } = await import('@tauri-apps/plugin-process');
          await relaunch();
        } catch {
          toast.error('Update failed to install', { id: TOAST_ID });
        }
      },
    },
  });
}
