// Small hand-drawn cat and dog marks (inline SVG, no image files).
// Decorative by default (aria-hidden); pass a title to make one meaningful.

type P = { size?: number; title?: string; className?: string };

function wrap(size: number, title: string | undefined, className: string | undefined, children: React.ReactNode, viewBox = "0 0 64 64") {
  return (
    <svg width={size} height={size} viewBox={viewBox} className={className} role={title ? "img" : undefined} aria-hidden={title ? undefined : true}>
      {title && <title>{title}</title>}
      {children}
    </svg>
  );
}

export function Cat({ size = 40, title, className }: P) {
  // Round tabby kitten: big sparkly eyes, pink ears and cheeks, little "ω" smile.
  return wrap(size, title, className, (
    <g strokeLinejoin="round" strokeLinecap="round">
      <path d="M10 30 Q7 10 12 5 Q20 8 27 17 Z" fill="#f5b97f" stroke="#8a5530" strokeWidth="2" />
      <path d="M54 30 Q57 10 52 5 Q44 8 37 17 Z" fill="#f5b97f" stroke="#8a5530" strokeWidth="2" />
      <path d="M13 22 Q12 13 14 9 Q19 12 23 17 Z" fill="#ffc9d6" />
      <path d="M51 22 Q52 13 50 9 Q45 12 41 17 Z" fill="#ffc9d6" />
      <ellipse cx="32" cy="37" rx="24" ry="21" fill="#f5b97f" stroke="#8a5530" strokeWidth="2" />
      <path d="M28 17 L29 23 M32 16 L32 23 M36 17 L35 23" stroke="#d98a4a" strokeWidth="2.4" />
      <ellipse cx="32" cy="45" rx="12" ry="8.5" fill="#fff3e3" />
      <ellipse cx="22.5" cy="35" rx="5" ry="6" fill="#2b1d14" />
      <ellipse cx="41.5" cy="35" rx="5" ry="6" fill="#2b1d14" />
      <circle cx="24.3" cy="32.6" r="2.1" fill="#fff" />
      <circle cx="43.3" cy="32.6" r="2.1" fill="#fff" />
      <circle cx="21" cy="37.6" r="1" fill="#fff" />
      <circle cx="40" cy="37.6" r="1" fill="#fff" />
      <ellipse cx="14.5" cy="43" rx="4.2" ry="2.6" fill="#ff9fb2" opacity="0.75" />
      <ellipse cx="49.5" cy="43" rx="4.2" ry="2.6" fill="#ff9fb2" opacity="0.75" />
      <path d="M29.6 41 Q32 39.8 34.4 41 Q32 44 29.6 41 Z" fill="#f07a93" />
      <path d="M32 43 Q32 46 29 46.5 Q27 46.5 26.5 45 M32 43 Q32 46 35 46.5 Q37 46.5 37.5 45" stroke="#8a5530" strokeWidth="1.6" fill="none" />
      <path d="M4 40 Q10 40 15 41.5 M5 46 Q10 45 15 44.5 M60 40 Q54 40 49 41.5 M59 46 Q54 45 49 44.5" stroke="#b07a52" strokeWidth="1.2" fill="none" />
    </g>
  ));
}

export function Dog({ size = 40, title, className }: P) {
  // Puppy: round golden face, big floppy ears, sparkly eyes, button nose, little tongue.
  return wrap(size, title, className, (
    <g strokeLinejoin="round" strokeLinecap="round">
      <path d="M15 14 Q3 15 4 30 Q5 42 12 45 Q18 45 19 36 L20 18 Z" fill="#a8693c" stroke="#5a3519" strokeWidth="2" />
      <path d="M49 14 Q61 15 60 30 Q59 42 52 45 Q46 45 45 36 L44 18 Z" fill="#a8693c" stroke="#5a3519" strokeWidth="2" />
      <ellipse cx="32" cy="35" rx="20" ry="20.5" fill="#f4c88d" stroke="#5a3519" strokeWidth="2" />
      <path d="M26 16 Q32 13 38 16 Q35 19 32 19 Q29 19 26 16 Z" fill="#e5ad6c" />
      <ellipse cx="32" cy="44" rx="11.5" ry="9" fill="#fff5e6" />
      <ellipse cx="23.5" cy="33" rx="4.6" ry="5.4" fill="#2b1d14" />
      <ellipse cx="40.5" cy="33" rx="4.6" ry="5.4" fill="#2b1d14" />
      <circle cx="25.2" cy="30.8" r="1.9" fill="#fff" />
      <circle cx="42.2" cy="30.8" r="1.9" fill="#fff" />
      <circle cx="22.2" cy="35.4" r="0.9" fill="#fff" />
      <circle cx="39.2" cy="35.4" r="0.9" fill="#fff" />
      <path d="M19.5 26.5 Q23 24.5 26.5 26 M37.5 26 Q41 24.5 44.5 26.5" stroke="#a8693c" strokeWidth="1.6" fill="none" />
      <ellipse cx="32" cy="40.5" rx="4" ry="3" fill="#2b1d14" />
      <ellipse cx="30.8" cy="39.6" rx="1.2" ry="0.7" fill="#7a6252" />
      <path d="M32 43.5 L32 45.5 M32 45.5 Q29 48 26.5 46 M32 45.5 Q35 48 37.5 46" stroke="#5a3519" strokeWidth="1.6" fill="none" />
      <path d="M30 47.2 Q32 53 34 47.2 Q32 48.2 30 47.2 Z" fill="#f08a9a" stroke="#5a3519" strokeWidth="1.1" />
      <ellipse cx="17" cy="41" rx="3.6" ry="2.3" fill="#ff9fb2" opacity="0.7" />
      <ellipse cx="47" cy="41" rx="3.6" ry="2.3" fill="#ff9fb2" opacity="0.7" />
    </g>
  ));
}

export function Paw({ size = 16, title, className, color = "currentColor" }: P & { color?: string }) {
  return wrap(size, title, className, (
    <g fill={color}>
      <ellipse cx="12" cy="17" rx="5" ry="4.3" />
      <ellipse cx="5.5" cy="10.5" rx="2.2" ry="2.8" />
      <ellipse cx="9.5" cy="6.5" rx="2.2" ry="2.8" />
      <ellipse cx="14.5" cy="6.5" rx="2.2" ry="2.8" />
      <ellipse cx="18.5" cy="10.5" rx="2.2" ry="2.8" />
    </g>
  ), "0 0 24 24");
}

export function SleepingCat({ size = 72 }: { size?: number }) {
  return (
    <svg width={size} height={size * 0.6} viewBox="0 0 120 72" aria-hidden>
      <path d="M14 58 Q10 30 44 28 Q70 26 86 40 Q100 52 96 60 Z" fill="#f2b680" stroke="#7a4a2a" strokeWidth="2.5" strokeLinejoin="round" />
      <path d="M96 60 Q112 58 110 44 Q108 36 100 38" fill="none" stroke="#7a4a2a" strokeWidth="5" strokeLinecap="round" />
      <path d="M96 60 Q112 58 110 44 Q108 36 100 38" fill="none" stroke="#f2b680" strokeWidth="2.5" strokeLinecap="round" />
      <path d="M22 34 L24 20 L34 30 Z" fill="#f2b680" stroke="#7a4a2a" strokeWidth="2" strokeLinejoin="round" />
      <path d="M40 30 L46 18 L52 30 Z" fill="#f2b680" stroke="#7a4a2a" strokeWidth="2" strokeLinejoin="round" />
      <path d="M26 42 Q29 44 32 42 M40 42 Q43 44 46 42" stroke="#2b2118" strokeWidth="2" fill="none" strokeLinecap="round" />
      <path d="M35 47 L37 47 L36 48.5 Z" fill="#e58a9e" />
      <text x="58" y="20" fontSize="12" fill="#7a8a99" fontFamily="sans-serif">z</text>
      <text x="66" y="12" fontSize="9" fill="#9aa5b1" fontFamily="sans-serif">z</text>
      <path d="M4 60 L116 60" stroke="#e2e0da" strokeWidth="2" />
    </svg>
  );
}

// A row of small paw prints used as a quiet divider.
export function PawTrail({ n = 5, color = "#c9d6d5" }: { n?: number; color?: string }) {
  return (
    <span className="paw-trail" aria-hidden>
      {Array.from({ length: n }).map((_, i) => (
        <span key={i} style={{ transform: `rotate(${i % 2 ? 18 : -12}deg) translateY(${i % 2 ? -3 : 3}px)` }}>
          <Paw size={12} color={color} />
        </span>
      ))}
    </span>
  );
}
