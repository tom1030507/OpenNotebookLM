This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Interface design

The research workspace uses quiet stone/graphite surfaces, Geist for the
interface, and a blue accent for citations and keyboard focus. The three-column
layout keeps sources, answers, and Studio outputs in view. Answers use a 15px
reading size with generous line spacing; compact controls use 16px Lucide icons,
and cards and controls use 12px and 8px corner radii. Light and dark themes share
the same hierarchy, and the mobile workspace uses the existing panel drawers.

The design polish follows [unslop](https://github.com/heydamir/unslop) by
[Damir Sokolovsky](https://heydamir.design/unslop), licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

## Getting Started

For a frontend-only preview, open `/login` and choose **Try offline demo**.
It loads bundled sample sources, a conversation with citations, and a note,
without starting FastAPI or Docker. You can also enter **demo / demo1234**;
if the backend is unreachable, sign-in falls back to the offline demo after
at most a two-second authentication wait. Rejected credentials still show an
error, and ordinary accounts always authenticate through the backend.

The workspace labels sample data as **Offline demo**. Uploads, changes,
exports, and generation require a running backend; sample content is read-only.
Use **Exit demo** or **Sign out** before signing in to your server.

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
