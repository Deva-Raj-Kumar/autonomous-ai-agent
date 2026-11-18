"use client";
// Cute Robot with Laptop illustration matching media_1794903349600_33affd6f.jpg

export default function RobotWithLaptop({ size = 180, className = "" }) {
  return (
    <div
      className={`robot-hero-illustration-wrap ${className}`}
      style={{ width: size, height: size * 0.85, position: "relative", margin: "0 auto" }}
    >
      <svg
        viewBox="0 0 260 210"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        style={{ width: "100%", height: "100%", overflow: "visible" }}
      >
        <defs>
          <filter id="robotGlowMain" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="6" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
          <filter id="softGreenGlow" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="12" result="blur" />
          </filter>
          <linearGradient id="laptopGrad" x1="80" y1="120" x2="180" y2="190" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#1e293b" />
            <stop offset="100%" stopColor="#0f172a" />
          </linearGradient>
          <linearGradient id="laptopScreenGrad" x1="100" y1="110" x2="160" y2="160" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#0284c7" />
            <stop offset="100%" stopColor="#0f766e" />
          </linearGradient>
          <linearGradient id="bubbleGrad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#065f46" stopOpacity="0.85" />
            <stop offset="100%" stopColor="#022c22" stopOpacity="0.9" />
          </linearGradient>
        </defs>

        {/* Ambient Glow behind robot */}
        <ellipse cx="130" cy="115" rx="65" ry="55" fill="#10b981" opacity="0.22" filter="url(#softGreenGlow)" />

        {/* Floating Chat Bubble Top Left */}
        <g opacity="0.9" transform="translate(15, 60)">
          <rect x="0" y="0" width="46" height="30" rx="8" fill="url(#bubbleGrad)" stroke="#10b981" strokeWidth="1.2" />
          <line x1="10" y1="11" x2="36" y2="11" stroke="#34d399" strokeWidth="2.5" strokeLinecap="round" />
          <line x1="10" y1="19" x2="26" y2="19" stroke="#6ee7b7" strokeWidth="2.5" strokeLinecap="round" />
        </g>

        {/* Floating Chat Bubble Top Right */}
        <g opacity="0.9" transform="translate(195, 25)">
          <rect x="0" y="0" width="48" height="32" rx="8" fill="url(#bubbleGrad)" stroke="#10b981" strokeWidth="1.2" />
          <line x1="10" y1="11" x2="38" y2="11" stroke="#34d399" strokeWidth="2.5" strokeLinecap="round" />
          <line x1="10" y1="20" x2="28" y2="20" stroke="#6ee7b7" strokeWidth="2.5" strokeLinecap="round" />
        </g>

        {/* Floating Chat Bubble Mid Right */}
        <g opacity="0.85" transform="translate(205, 80)">
          <rect x="0" y="0" width="44" height="26" rx="7" fill="url(#bubbleGrad)" stroke="#10b981" strokeWidth="1" />
          <line x1="9" y1="10" x2="35" y2="10" stroke="#34d399" strokeWidth="2" strokeLinecap="round" />
          <line x1="9" y1="17" x2="24" y2="17" stroke="#6ee7b7" strokeWidth="2" strokeLinecap="round" />
        </g>

        {/* Tiny Sparkles */}
        <circle cx="58" cy="45" r="2" fill="#34d399" opacity="0.8" />
        <circle cx="218" cy="130" r="1.5" fill="#38bdf8" opacity="0.7" />
        <circle cx="190" cy="15" r="2.5" fill="#a7f3d0" opacity="0.9" filter="url(#robotGlowMain)" />

        {/* Robot Antenna */}
        <circle cx="130" cy="32" r="5" fill="#34d399" filter="url(#robotGlowMain)" />
        <rect x="127.5" y="36" width="5" height="15" rx="2.5" fill="#a7f3d0" />

        {/* Robot Head Outer Body */}
        <rect
          x="88"
          y="48"
          width="84"
          height="68"
          rx="28"
          fill="#ffffff"
          stroke="#10b981"
          strokeWidth="3.5"
          filter="drop-shadow(0 4px 14px rgba(16, 185, 129, 0.2))"
        />

        {/* Left & Right Headphone Ears */}
        <rect x="78" y="64" width="10" height="34" rx="5" fill="#10b981" />
        <rect x="172" y="64" width="10" height="34" rx="5" fill="#10b981" />

        {/* Face Screen Visor */}
        <rect x="99" y="58" width="62" height="46" rx="18" fill="#042f2e" stroke="#064e3b" strokeWidth="1.5" />

        {/* Glowing Eyes */}
        <rect x="110" y="70" width="9" height="15" rx="4.5" fill="#34d399" filter="url(#robotGlowMain)" />
        <rect x="141" y="70" width="9" height="15" rx="4.5" fill="#34d399" filter="url(#robotGlowMain)" />

        {/* Smiling Mouth */}
        <path d="M123 90 C 127 94, 133 94, 137 90" stroke="#6ee7b7" strokeWidth="2.5" strokeLinecap="round" />

        {/* Robot Torso / Body */}
        <path
          d="M106 116 C 106 116, 112 114, 130 114 C 148 114, 154 116, 154 116 L 164 165 C 164 165, 148 170, 130 170 C 112 170, 96 165, 96 165 Z"
          fill="#f8fafc"
          stroke="#cbd5e1"
          strokeWidth="2"
        />

        {/* Chest Emblem */}
        <circle cx="130" cy="138" r="8" fill="#10b981" opacity="0.2" />
        <circle cx="130" cy="138" r="4.5" fill="#10b981" filter="url(#robotGlowMain)" />

        {/* Robot Arms resting on table / typing */}
        <path d="M96 130 C 90 145, 105 165, 120 162" stroke="#ffffff" strokeWidth="10" strokeLinecap="round" />
        <path d="M164 130 C 170 145, 155 165, 140 162" stroke="#ffffff" strokeWidth="10" strokeLinecap="round" />

        {/* Laptop Screen (angled open) */}
        <path
          d="M 120 128 L 175 125 L 165 175 L 110 175 Z"
          fill="url(#laptopGrad)"
          stroke="#334155"
          strokeWidth="1.5"
          filter="drop-shadow(0 6px 14px rgba(0, 0, 0, 0.45))"
        />

        {/* Glowing Apple / AI logo on back of laptop */}
        <circle cx="142" cy="148" r="4.5" fill="#38bdf8" filter="url(#robotGlowMain)" />

        {/* Laptop Keyboard / Base */}
        <path
          d="M 105 174 L 172 174 L 162 188 L 95 188 Z"
          fill="#1e293b"
          stroke="#0f172a"
          strokeWidth="1.5"
        />
        {/* Trackpad */}
        <rect x="124" y="180" width="16" height="5" rx="1" fill="#334155" />
      </svg>
    </div>
  );
}
