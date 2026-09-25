import { notFound } from 'next/navigation';
import { HomeContent } from '../../components/HomeContent';
import { LegacyContent } from '../../components/LegacyContent';
import { PageStyles } from '../../components/PageStyles';
import { PAGE_ROUTES, findPage, readPage } from '../../lib/pages.mjs';

type PageProps = { params: Promise<{ slug: string[] }> };
export const dynamicParams = false;

export function generateStaticParams() {
  const canonical = PAGE_ROUTES.filter(page => page.route !== '/')
    .map(page => ({ slug: page.route.split('/').filter(Boolean) }));
  // Nginx handles legacy redirects in production; dev accepts old bookmarks too.
  return process.env.NODE_ENV === 'development'
    ? [...canonical, ...PAGE_ROUTES.map(page => ({ slug: page.file.split('/') }))]
    : canonical;
}

export async function generateMetadata({ params }: PageProps) {
  const { slug } = await params;
  const entry = findPage(slug.join('/'));
  if (!entry) return {};
  const page = readPage(entry.file);
  return { title: `${page.title} — TestLogica`, description: page.description };
}

export default async function ContentPage({ params }: PageProps) {
  const { slug } = await params;
  const entry = findPage(slug.join('/'));
  if (!entry) notFound();
  const page = readPage(entry.file);
  return <>
    <PageStyles styles={page.styles} />
    {entry.file === 'index.html' ? <HomeContent /> : <LegacyContent
      html={page.html} scripts={page.scripts} bodyAttributes={page.bodyAttributes}
    />}
  </>;
}
