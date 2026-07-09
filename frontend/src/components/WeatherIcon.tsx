import type { Condition } from '../lib/data'

interface Props {
  cond: Condition
  size?: number
}

export function WeatherIcon({ cond, size = 40 }: Props) {
  const shared = {
    width: size,
    height: size,
    viewBox: '0 0 48 48',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.8,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  }
  switch (cond) {
    case 'Clear':
      return (
        <svg {...shared}>
          <circle cx="24" cy="22" r="8" />
          <path d="M24 6v4M24 34v0M8 22h4M36 22h4M13 11l2.5 2.5M35 11l-2.5 2.5" />
        </svg>
      )
    case 'Partly Cloudy':
      return (
        <svg {...shared}>
          <circle cx="18" cy="17" r="6" />
          <path d="M18 7v3M8 17h3M11 10l2 2" />
          <path d="M18 36h14a6 6 0 0 0 .5-12A9 9 0 0 0 16 26a5 5 0 0 0 2 10z" />
        </svg>
      )
    case 'Cloudy':
      return (
        <svg {...shared}>
          <path d="M16 34h16a7 7 0 0 0 1-13.9A10 10 0 0 0 13 22a6 6 0 0 0 3 12z" />
        </svg>
      )
    case 'Rain':
      return (
        <svg {...shared}>
          <path d="M16 28h16a7 7 0 0 0 1-13.9A10 10 0 0 0 13 16a6 6 0 0 0 3 12z" />
          <path d="M17 34l-1.5 4M24 34l-1.5 4M31 34l-1.5 4" />
        </svg>
      )
    case 'Fog':
      return (
        <svg {...shared}>
          <path d="M16 24h16a7 7 0 0 0 1-13.9A10 10 0 0 0 13 12a6 6 0 0 0 3 12z" />
          <path d="M12 32h24M14 38h20" />
        </svg>
      )
    case 'Wind':
      return (
        <svg {...shared}>
          <path d="M4 20h22a5 5 0 1 0-5-5" />
          <path d="M4 28h30a5 5 0 1 1-5 5" />
          <path d="M4 36h14" />
        </svg>
      )
    case 'Snow':
      return (
        <svg {...shared}>
          <path d="M16 26h16a7 7 0 0 0 1-13.9A10 10 0 0 0 13 14a6 6 0 0 0 3 12z" />
          <path d="M18 33v0M24 36v0M30 33v0M18 38v0M30 38v0M24 32v0" strokeWidth={3} />
        </svg>
      )
    case 'Ice':
      return (
        <svg {...shared}>
          <path d="M24 6v36M24 6l-5 5M24 6l5 5M24 42l-5-5M24 42l5-5M8 15l32 18M8 15l1 7M8 15l7-1M40 33l-1-7M40 33l-7 1M40 15L8 33M40 15l-7-1M40 15l-1 7M8 33l7 1M8 33l1-7" />
        </svg>
      )
  }
}
