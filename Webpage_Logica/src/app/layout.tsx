import type { ReactNode } from 'react';
import { SiteRuntimeProvider } from '../components/SiteRuntimeProvider';
import { SiteSettings } from '../components/SiteSettings';

export const metadata = {
  title: 'TestLogica',
  description: 'Lezioni, esercizi e strumenti per imparare la logica.',
  icons: { icon: '/favicon.ico' },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="it">
      <body>
        <SiteRuntimeProvider>
          {children}
          <SiteSettings />
        </SiteRuntimeProvider>
      </body>
    </html>
  );
}
