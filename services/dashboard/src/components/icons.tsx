import type { ReactNode } from "react";

const Svg = ({ children, size = 22 }: { children: ReactNode; size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {children}
  </svg>
);

export const BatteryLogo = () => (
  <svg width="40" height="52" viewBox="0 0 40 52" aria-hidden="true">
    <rect x="13" y="1" width="14" height="6" rx="2" fill="#3fbf6a" />
    <rect x="3" y="6" width="34" height="44" rx="6" fill="#1f7a45" stroke="#4ade80" strokeWidth="2" />
    <rect x="7" y="10" width="26" height="20" rx="3" fill="#3fbf6a" />
    <path d="M22 14 L15 28 H21 L18 40 L27 24 H21 Z" fill="#0b1220" />
  </svg>
);
export const ThermometerIcon = () => (
  <Svg><path d="M14 14.8V5a2 2 0 0 0-4 0v9.8a4 4 0 1 0 4 0Z" /><path d="M12 9v8" /></Svg>
);
export const ShieldIcon = () => (
  <Svg><path d="M12 3 4.5 6v5.5c0 4.6 3.1 8.2 7.5 9.5 4.4-1.3 7.5-4.9 7.5-9.5V6L12 3Z" /><path d="m9 12 2.2 2.2L15.5 10" /></Svg>
);
export const SignalIcon = () => (
  <Svg><circle cx="12" cy="12" r="1.6" /><path d="M8.5 8.5a5 5 0 0 0 0 7M15.5 8.5a5 5 0 0 1 0 7M5.5 5.5a9 9 0 0 0 0 13M18.5 5.5a9 9 0 0 1 0 13" /></Svg>
);
export const DatabaseIcon = () => (
  <Svg><ellipse cx="12" cy="6" rx="7" ry="3" /><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" /></Svg>
);
export const ChartIcon = () => (
  <Svg><path d="M3 3v18h18" /><path d="m7 15 4-5 3 3 5-7" /></Svg>
);
export const ClockIcon = () => (
  <Svg><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></Svg>
);
export const FlowIcon = () => (
  <Svg><circle cx="12" cy="5" r="2.2" /><circle cx="5" cy="19" r="2.2" /><circle cx="19" cy="19" r="2.2" /><path d="M12 7.2v4.3M12 11.5 6 17M12 11.5 18 17" /></Svg>
);
export const SensorIcon = () => (
  <Svg size={30}><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8M12 16v4" /><circle cx="8" cy="10" r="1" /><circle cx="12" cy="10" r="1" /><circle cx="16" cy="10" r="1" /></Svg>
);
export const BrokerIcon = () => (
  <Svg size={30}><path d="M7 18a4 4 0 0 1-.6-7.9A6 6 0 0 1 18 9.5 4.3 4.3 0 0 1 17.5 18H7Z" /></Svg>
);
export const AdapterIcon = () => (
  <Svg size={30}><path d="M4 8h12M12 4l4 4-4 4M20 16H8M12 12l-4 4 4 4" /></Svg>
);
export const ServerIcon = () => (
  <Svg size={30}><rect x="3" y="4" width="18" height="6" rx="1.5" /><rect x="3" y="14" width="18" height="6" rx="1.5" /><path d="M7 7h.01M7 17h.01" /></Svg>
);
export const BridgeIcon = () => (
  <Svg size={30}><path d="M3 17c3-8 15-8 18 0M3 17h18M7 17v-4M12 17v-6M17 17v-4" /></Svg>
);
export const DisplayIcon = () => (
  <Svg size={30}><rect x="3" y="5" width="18" height="12" rx="2" /><path d="M8 21h8M12 17v4" /></Svg>
);
