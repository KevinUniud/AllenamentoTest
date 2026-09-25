import { PageStyles } from '../components/PageStyles';

export default function NotFound() {
  return <>
    <PageStyles styles={['/styles/base.css', '/styles/components.css', '/styles/themes.css']} />
    <main id="main-content" tabIndex={-1}>
      <h1>Pagina non trovata</h1>
      <p>Il collegamento non corrisponde a una pagina di TestLogica.</p>
      <a className="btn-wide" href="/">Torna all’indice</a>
    </main>
  </>;
}
