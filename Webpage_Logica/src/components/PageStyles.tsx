export function PageStyles({ styles }: { styles: string[] }) {
  return <>{styles.map(href => <link key={href} rel="stylesheet" href={href} />)}</>;
}
