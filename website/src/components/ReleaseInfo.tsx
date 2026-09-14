import { useEffect, useState } from 'react';
import { fetchLatestRelease, formatDate, formatSize, type OrionRelease } from '../lib/release';
import { RELEASES_URL } from '../lib/site';

/** Version, date and size of the newest installer on GitHub Releases. */
export default function ReleaseInfo() {
  const [release, setRelease] = useState<OrionRelease | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');

  useEffect(() => {
    fetchLatestRelease()
      .then((r) => {
        setRelease(r);
        setState('ready');
      })
      .catch(() => setState('error'));
  }, []);

  if (state === 'loading') return <p className="text-sm text-[var(--color-faint)]">Finding the latest build…</p>;
  if (state === 'error' || !release)
    return (
      <p className="text-sm text-[var(--color-faint)]">
        Couldn't load release details. All builds are on{' '}
        <a className="text-[var(--color-cyan-soft)] underline" href={RELEASES_URL}>
          GitHub Releases
        </a>
        .
      </p>
    );

  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
      <div>
        <dt className="text-[var(--color-faint)]">Version</dt>
        <dd className="font-semibold text-white">
          {release.version}
          {release.prerelease && <span className="ml-2 text-xs font-medium text-[#fcd34d]">pre-release</span>}
        </dd>
      </div>
      <div>
        <dt className="text-[var(--color-faint)]">Released</dt>
        <dd className="text-white">{formatDate(release.publishedAt) || '—'}</dd>
      </div>
      <div>
        <dt className="text-[var(--color-faint)]">Installer</dt>
        <dd className="text-white">{release.downloadUrl ? formatSize(release.sizeBytes) : 'Not attached yet'}</dd>
      </div>
      <div>
        <dt className="text-[var(--color-faint)]">Notes</dt>
        <dd>
          <a className="text-[var(--color-cyan-soft)] underline underline-offset-2" href={release.pageUrl}>
            Release page
          </a>
        </dd>
      </div>
    </dl>
  );
}
