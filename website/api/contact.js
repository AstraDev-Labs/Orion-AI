// POST /api/contact: delivers the website's contact form to Orion's inbox.
//
// Set these in the Vercel project (Settings → Environment Variables):
//   CONTACT_SMTP_USER  the Gmail address that sends and receives the messages
//   CONTACT_SMTP_PASS  a Google app password for that account
//   CONTACT_TO         optional: deliver to a different address
import nodemailer from 'nodemailer';
import { createContactHandler } from './_lib/contact.js';

let transport;

function sendMail(mail) {
  transport ??= nodemailer.createTransport({
    host: process.env.CONTACT_SMTP_HOST || 'smtp.gmail.com',
    port: Number(process.env.CONTACT_SMTP_PORT || 465),
    secure: true,
    auth: { user: process.env.CONTACT_SMTP_USER, pass: (process.env.CONTACT_SMTP_PASS || '').replace(/\s+/g, '') },
  });
  return transport.sendMail(mail);
}

export const POST = createContactHandler({ sendMail, env: process.env });
