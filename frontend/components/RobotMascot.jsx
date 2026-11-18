"use client";
// Cute Robot Avatar & Mascot matching Autonomous AI Agent branding

export default function RobotMascot({ size = 42, className = "" }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-label="Autonomous AI Agent Mascot"
    >
      <defs>
        <linearGradient id="robotScreenGrad" x1="28" y1="36" x2="72" y2="68" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#064e3b" />
          <stop offset="100%" stopColor="#022c22" />
        </linearGradient>
        <filter id="robotGlow" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="3" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
      </defs>

      {/* Antenna */}
      <circle cx="50" cy="14" r="5" fill="#10b981" filter="url(#robotGlow)" />
      <rect x="47.5" y="18" width="5" height="12" rx="2.5" fill="#34d399" />

      {/* Head Outer Frame */}
      <rect
        x="18"
        y="26"
        width="64"
        height="52"
        rx="22"
        fill="#ffffff"
        stroke="#10b981"
        strokeWidth="3.5"
      />

      {/* Left & Right Headphone / Ears */}
      <rect x="10" y="38" width="8" height="26" rx="4" fill="#10b981" />
      <rect x="82" y="38" width="8" height="26" rx="4" fill="#10b981" />

      {/* Dark Visor / Face Screen */}
      <rect
        x="26"
        y="34"
        width="48"
        height="36"
        rx="14"
        fill="url(#robotScreenGrad)"
      />

      {/* Glowing Smiling Eyes */}
      <rect x="34" y="44" width="7" height="12" rx="3.5" fill="#34d399" filter="url(#robotGlow)" />
      <rect x="59" y="44" width="7" height="12" rx="3.5" fill="#34d399" filter="url(#robotGlow)" />

      {/* Friendly Smile */}
      <path
        d="M44 60 C 47 64, 53 64, 56 60"
        stroke="#6ee7b7"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

