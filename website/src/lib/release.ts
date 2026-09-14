import { REPO, RELEASES_URL } from './site';

export type OrionRelease = {
  version: string;
  name: string;
  publishedAt: string | null;
  prerelease: boolean;
  pageUrl: string;
  /** Direct link to OrionSetup-*.exe, or null when no installer is attached yet. */
  downloadUrl: string | null;
  sizeBytes: number | null;
  fileName: string | null;
};

const CACHE_KEY = 'orion-release-v1';
const INSTALLER = /^OrionSetup.*\.exe$/i;
const TIMEOUT_MS = 8000;

let pending: Promise<OrionRelease | null> | null = null;

/**
 * The newest GitHub release that has the Windows installer attached.
 *
 * Reads the release list rather than /releases/latest: alpha builds are
 * published as pre-releases, which /releases/latest skips.
 *
 * Every download button on a page shares one request, and a failure is not
 * retried until the next page load: GitHub allows 60 anonymous API calls an
 * hour per visitor.
 */
export function fetchLatestRelease(): Promise<OrionRelease | null> {
  pending ??= loadRelease();
  return pending;
}

async function loadRelease(): Promise<OrionRelease | null> {
  try {
    const cached = sessionStorage.getItem(CACHE_KEY);
    if (cached) return JSON.parse(cached) as OrionRelease;
  } catch {
    /* no storage */
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(`https://api.github.com/repos/${REPO}/releases?per_page=15`, {
      headers: { Accept: 'application/vnd.github+json' },
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) throw new Error(`GitHub returned ${res.status}`);
  const releases = (await res.json()) as Array<{
    tag_name: string;
    name: string | null;
    draft: boolean;
    prerelease: boolean;
    published_at: string | null;
    html_url: string;
    assets: Array<{ name: string; browser_download_url: string; size: number }>;
  }>;
  const published = releases.filter((r) => !r.draft);
  const withInstaller = published.find((r) => r.assets.some((a) => INSTALLER.test(a.name)));
  const pick = withInstaller ?? published[0];
  if (!pick) return null;
  const asset = pick.assets.find((a) => INSTALLER.test(a.name)) ?? null;
  const release: OrionRelease = {
    version: pick.tag_name.replace(/^v/i, ''),
    name: pick.name || pick.tag_name,
    publishedAt: pick.published_at,
    prerelease: pick.prerelease,
    pageUrl: pick.html_url || RELEASES_URL,
    downloadUrl: asset?.browser_download_url ?? null,
    sizeBytes: asset?.size ?? null,
    fileName: asset?.name ?? null,
  };
  try {
    sessionStorage.setItem(CACHE_KEY, JSON.stringify(release));
  } catch {
    /* no storage */
  }
  return release;
}

export function formatSize(bytes: number | null): string {
  if (!bytes) return '';
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDate(iso: string | null): string {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
}
