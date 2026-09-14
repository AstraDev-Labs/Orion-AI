// @ts-check
import { defineConfig } from 'astro/config';
import react from '@astrojs/react';
import starlight from '@astrojs/starlight';
import tailwindcss from '@tailwindcss/vite';
import { satteri } from '@astrojs/markdown-satteri';

// Where the site is published. Defaults to GitHub Pages for the repository;
// set SITE_URL (and BASE_PATH="/" ) when moving to a custom domain.
const site = process.env.SITE_URL || 'https://astradev-labs.github.io';
const base = process.env.BASE_PATH ?? '/Orion-AI';
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
  trailingSlash: 'ignore',
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
