import { HomeContent } from '../components/HomeContent';
import { PageStyles } from '../components/PageStyles';
import { readPage } from '../lib/pages.mjs';

export const metadata = { title: 'Indice — TestLogica', description: 'Accesso rapido a lezioni ed esercizi.' };

export default function HomePage() {
  const page = readPage('index.html');
  return <><PageStyles styles={page.styles} /><HomeContent /></>;
}
