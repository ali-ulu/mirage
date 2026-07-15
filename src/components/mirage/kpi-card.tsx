/**
 * MIRAGE Dashboard — KpiCard Component
 *
 * Neo-Brutalist design principles:
 *   - Sharp corners (rounded-none)
 *   - Thick black border (border-2)
 *   - Hard offset shadow (no blur)
 *   - Monospace font for numeric values
 *   - High contrast (black on white)
 *   - Optional accent color via `variant` prop
 */
import { cn } from '@/lib/utils'

export type KpiCardVariant = 'default' | 'danger' | 'success' | 'warning'

export interface KpiCardProps {
  label: string
  value: string | number
  sublabel?: string
  variant?: KpiCardVariant
  className?: string
}

const variantStyles: Record<KpiCardVariant, string> = {
  default: 'border-black bg-white text-black',
  danger: 'border-black bg-red-100 text-black',
  success: 'border-black bg-emerald-100 text-black',
  warning: 'border-black bg-yellow-100 text-black',
}

const variantAccent: Record<KpiCardVariant, string> = {
  default: 'bg-black',
  danger: 'bg-red-600',
  success: 'bg-emerald-600',
  warning: 'bg-yellow-500',
}

export function KpiCard({
  label,
  value,
  sublabel,
  variant = 'default',
  className,
}: KpiCardProps) {
  const formattedValue =
    typeof value === 'number'
      ? value.toLocaleString('en-US')
      : value

  return (
    <div
      data-testid="kpi-card"
      className={cn(
        'border-2 rounded-none shadow-[6px_6px_0_0_#000] p-4 relative',
        'font-mono',
        variantStyles[variant],
        className,
      )}
    >
      {/* Accent stripe (top) */}
      <div className={cn('absolute top-0 left-0 right-0 h-1', variantAccent[variant])} />

      <div className="pt-2">
        <div className="text-xs font-bold uppercase tracking-widest text-black/70">
          {label}
        </div>
        <div
          data-testid="kpi-value"
          className="font-mono text-3xl md:text-4xl font-black mt-1 leading-none"
        >
          {formattedValue}
        </div>
        {sublabel && (
          <div
            data-testid="kpi-sublabel"
            className="text-[10px] font-mono uppercase tracking-wider text-black/60 mt-2"
          >
            {sublabel}
          </div>
        )}
      </div>
    </div>
  )
}
