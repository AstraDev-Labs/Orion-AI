/** Facts about Orion used across the site. Keep in step with the installer. */

export const REPO = 'AstraDev-Labs/Orion-AI';
export const REPO_URL = `https://github.com/${REPO}`;
export const RELEASES_URL = `${REPO_URL}/releases`;
export const ISSUES_URL = `${REPO_URL}/issues`;
export const NEW_ISSUE_URL = `${REPO_URL}/issues/new`;

export const VERSION = '1.0.1';
export const STAGE = 'Alpha';

/** A link inside the site, respecting the base path (GitHub Pages). */
export function url(path = '/'): string {
  const base = import.meta.env.BASE_URL.replace(/\/$/, '');
  const clean = path.startsWith('/') ? path : `/${path}`;
  return `${base}${clean}` || '/';
}

export const NAV = [
  { label: 'Features', href: '/#features' },
  { label: 'Requirements', href: '/system-requirements' },
  { label: 'Docs', href: '/docs' },
  { label: 'Security', href: '/security' },
  { label: 'About', href: '/about' },
];

export const FOOTER = [
  {
    title: 'Product',
    links: [
      { label: 'Download', href: '/download' },
      { label: 'System requirements', href: '/system-requirements' },
      { label: 'Changelog', href: '/changelog' },
      { label: 'Roadmap', href: '/roadmap' },
    ],
  },
  {
    title: 'Resources',
    links: [
      { label: 'Documentation', href: '/docs' },
      { label: 'FAQ', href: '/faq' },
      { label: 'Developers', href: '/developers' },
      { label: 'Press kit', href: '/press' },
    ],
  },
  {
    title: 'Community',
    links: [
      { label: 'About', href: '/about' },
      { label: 'Feature wishlist', href: '/wishlist' },
      { label: 'Contact', href: '/contact' },
    ],
  },
  {
    title: 'Legal',
    links: [
      { label: 'Privacy policy', href: '/privacy' },
      { label: 'Terms of use', href: '/terms' },
      { label: 'Security', href: '/security' },
    ],
  },
];
