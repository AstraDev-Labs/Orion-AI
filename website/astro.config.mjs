// @ts-check
import { defineConfig } from 'astro/config';
import react from '@astrojs/react';
import starlight from '@astrojs/starlight';
import tailwindcss from '@tailwindcss/vite';
import { satteri } from '@astrojs/markdown-satteri';

// Where the site is published (Vercel). SITE_URL wins, so set it in the Vercel
// project once a custom domain is attached; otherwise Vercel's production
// domain is used. BASE_PATH is only needed when serving from a sub-folder.
const vercelDomain = process.env.VERCEL_PROJECT_PRODUCTION_URL || process.env.VERCEL_URL;
const publicSite = process.env.SITE_URL || (vercelDomain ? `https://${vercelDomain}` : '');
const isBuild = process.argv.includes('build');
if (isBuild && !publicSite) {
  // Without a public address, canonical links, social previews, the sitemap
  // and robots.txt would point at localhost on the live site.
  throw new Error(
    'The website needs its public address to build. Set SITE_URL (for example ' +
      'https://orion-ai.vercel.app), or on Vercel keep "Automatically expose System ' +
      'Environment Variables" turned on.',
  );
}
if (publicSite && /localhost|127\.0\.0\.1/.test(publicSite)) {
  throw new Error(`SITE_URL must be the public website address, not ${publicSite}.`);
}
const site = publicSite || 'http://localhost:4321';
const base = process.env.BASE_PATH || '/';
const basePrefix = base.replace(/\/$/, '');

/** Markdown links like `/terms` point at the site root; prefix them with the base path. */
const baseLinks = {
  name: 'orion-base-links',
  element: [
    {
      filter: ['a', 'img'],
      visit(node, ctx) {
        for (const attr of ['href', 'src']) {
          const value = node.properties?.[attr];
          if (typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') && basePrefix && !value.startsWith(`${basePrefix}/`)) {
            ctx.setProperty(node, attr, `${basePrefix}${value}`);
          }
        }
      },
    },
  ],
};

export default defineConfig({
  site,
  base,
  trailingSlash: 'never',
  markdown: { processor: satteri({ hastPlugins: [baseLinks] }) },
  integrations: [
    react(),
    starlight({
      title: 'Orion Docs',
      description: 'How to install, use and troubleshoot Orion, the on-device AI assistant.',
      logo: { src: './src/assets/orion-logo.png', alt: 'Orion' },
      favicon: '/favicon.ico',
      // The site has its own 404 page (src/pages/404.astro).
      disable404Route: true,
      customCss: ['./src/styles/starlight.css'],
      social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/AstraDev-Labs/Orion-AI' }],
      editLink: { baseUrl: 'https://github.com/AstraDev-Labs/Orion-AI/edit/V1.0.1A/website/' },
      sidebar: [
        { label: '← Orion website', link: '/' },
        {
          label: 'Getting started',
          items: [
            { label: 'Install Orion', slug: 'docs' },
            { label: 'First launch', slug: 'docs/first-launch' },
            { label: 'System requirements', link: '/system-requirements' },
          ],
        },
        {
          label: 'Using Orion',
          items: [
            { label: 'Talking to Orion', slug: 'docs/voice' },
            { label: 'Actions and approvals', slug: 'docs/actions' },
            { label: 'Connections', slug: 'docs/connections' },
            { label: 'Tray, updates and startup', slug: 'docs/tray-and-updates' },
          ],
        },
        {
          label: 'Help',
          items: [
            { label: 'Troubleshooting', slug: 'docs/troubleshooting' },
            { label: 'Uninstall', slug: 'docs/uninstall' },
            { label: 'Build from source', slug: 'docs/build-from-source' },
          ],
        },
      ],
    }),
  ],
  vite: {
    plugins: [tailwindcss()],
  },
});
